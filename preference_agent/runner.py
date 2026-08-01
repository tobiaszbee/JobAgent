import sys
import logging

logger = logging.getLogger(__name__)

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_DISTILL_MODEL
from collector.utils import build_excerpt
from db.repositories import job_repository, preference_repository, dismissed_item_repository
from preference_agent.profile import _DISTILL_TOOL, render_signals

_SYSTEM = """\
You distill job application history into a structured preference profile consumed by another AI evaluator.
Optimize for: maximum information density, unambiguous signals, evidence-backed confidence.

Analyze ALL dimensions relevant to job-candidate fit, including but not limited to:
- Compensation/rate patterns (explicit amounts, "competitive" language, missing rate)
- Company type (product vs agency/staffing/outsourcing vs enterprise)
- Contract form (B2B, employment, contract-to-hire)
- Work culture (async, startup pace, corporate, team size, meeting culture)
- Tech stack and seniority match
- Domain/industry fit
- Role responsibilities and scope
- Any other patterns consistently visible in the feedback

Do NOT include: location, remote/on-site, geography, visa — filtered upstream.

You may also see a DISMISSED SCORE FACTORS section: cases where the candidate looked at a specific
pro/con from a past AI evaluation and explicitly said it doesn't apply to them, with a reason. This is
the strongest signal available — direct correction, not inference. Fold each into whichever dimension it
belongs to (e.g. dismissing a timezone/right-to-work con → work_culture; dismissing a company-size con →
company_type) rather than repeating the dismissed text verbatim, and weight it at least conf=HIGH.

Use ONLY these dimension names (sub-values are free-form):
  compensation, company_type, contract_form, work_culture, tech_stack, seniority, domain, role_scope

Signal types and required fields:
- ACCEPT/REJECT: type, dim, value, conf (ABSOLUTE/HIGH/MEDIUM/LOW), n_match/n_total (X matching / total in class)
- INFER: type, dim, value (inferred value), n_total (evidence count) — for patterns not directly stated by user
- NEUTRAL: type, dim — dimension with no clear preference pattern

Rules:
- One signal per dimension (or per distinct value if same dim splits ACCEPT/REJECT)
- Infer dealbreakers from consistent rejections + repeated user reasons
- Emit INFER with numeric values ONLY when the number appears explicitly in the evidence
- Emit NEUTRAL for every dimension with no clear pattern — do not omit any
- LEVEL values: ABSOLUTE(100% consistent), HIGH(>80%), MEDIUM(60-80%), LOW(<60%)

Calibration example (fictional data — do not copy these values):
Input:
  APPLIED (3): all product SaaS companies, B2B contracts
  REJECTED (5): 4 outsourcing agencies ("body shop, bad rates"), 1 large enterprise ("too bureaucratic")
Expected signals:
  {type=ACCEPT, dim=company_type, value=product_saas, conf=HIGH, n_match=3, n_total=3}
  {type=REJECT, dim=company_type, value=agency_outsourcing, conf=HIGH, n_match=4, n_total=5, note="body shop, bad rates"}
  {type=REJECT, dim=company_type, value=enterprise, conf=LOW, n_match=1, n_total=5, note="too bureaucratic"}
  {type=INFER, dim=work_culture, value=async_preferred, n_total=1}
  {type=NEUTRAL, dim=compensation}
  {type=NEUTRAL, dim=contract_form}
  {type=NEUTRAL, dim=tech_stack}
  {type=NEUTRAL, dim=seniority}
  {type=NEUTRAL, dim=domain}
  {type=NEUTRAL, dim=role_scope}

Submit your analysis using the submit_profile tool.\
"""


_DESC_LIMIT = 1500
_MAX_APPLIED = 50
_MAX_REJECTED = 50


def _job_line(job: dict, include_reason: bool = False) -> str:
    title = job.get("title", "?")
    company = job.get("company", "?")
    location = job.get("location", "")
    description = build_excerpt(job.get("description"), job.get("source")).replace("\n", " ").strip()
    job_parts = [f'"{title}" @ {company}']
    if location:
        job_parts.append(f"[{location}]")
    if description:
        job_parts.append(f"| {description[:_DESC_LIMIT]}")
    if include_reason:
        reason = (job.get("rejection_reason") or job.get("score_reason") or "").strip()
        if reason:
            job_parts.append(f"| reason: {reason[:120]}")
    return " ".join(job_parts)


def _build_dismissed_section(items: list[dict]) -> str:
    if not items:
        return ""
    lines = ["DISMISSED SCORE FACTORS (candidate says these specific pros/cons don't apply to them):"]
    for it in items:
        kind = "CON" if it["item_type"] == "con" else "PRO"
        title = it.get("title", "?")
        company = it.get("company", "?")
        lines.append(
            f'  - {kind} on "{title}" @ {company}: "{it["item_text"]}" '
            f'— dismissed because: "{it["reason"]}"'
        )
    return "\n\n" + "\n".join(lines)


def _build_prompt(applied: list[dict], rejected: list[dict], applied_total: int, rejected_total: int) -> str:
    """`applied`/`rejected` arrive already capped to at most _MAX_APPLIED/_MAX_REJECTED
    (most-recent-first) and description-truncated server-side — see
    job_repository.get_all_feedback(). `applied_total`/`rejected_total` are the true,
    uncapped counts, only for the "N older omitted" messaging below."""
    sections = []
    if applied:
        omitted = applied_total - len(applied)
        header = f"APPLIED ({applied_total} jobs, showing {len(applied)} most recent" + (f", {omitted} older omitted" if omitted else "") + "):"
        lines = [header]
        for job in applied:
            lines.append(f"  {_job_line(job)}")
        sections.append("\n".join(lines))
    else:
        sections.append("APPLIED (0 jobs): none yet")

    if rejected:
        omitted = rejected_total - len(rejected)
        header = f"REJECTED ({rejected_total} jobs, showing {len(rejected)} most recent" + (f", {omitted} older omitted" if omitted else "") + "):"
        lines = [header]
        for job in rejected:
            lines.append(f"  {_job_line(job, include_reason=True)}")
        sections.append("\n".join(lines))
    else:
        sections.append("REJECTED (0 jobs): none yet")

    return "\n\n".join(sections)


def run() -> dict:
    # applied/rejected are capped samples (most-recent-first, description-truncated
    # server-side); applied_total/rejected_total are the true counts, needed for
    # detecting "did anything change since last distillation" — the capped sample's
    # own length stays pinned at the cap forever once a candidate has more than
    # _MAX_APPLIED/_MAX_REJECTED decisions, which would silently break that check.
    applied, rejected = job_repository.get_all_feedback(limit_applied=_MAX_APPLIED, limit_rejected=_MAX_REJECTED)
    stats = job_repository.get_stats()
    applied_total = stats["applied"]
    rejected_total = stats["rejected"]
    dismissed_total = dismissed_item_repository.count_all()
    if not applied_total and not rejected_total and not dismissed_total:
        logger.info("No feedback data yet — apply, reject, or dismiss a score factor first.")
        return {"ok": False, "reason": "no_data"}

    previous_profile = preference_repository.get_latest()
    if previous_profile:
        if (applied_total == previous_profile["applied_count"] and
                rejected_total == previous_profile["rejected_count"] and
                dismissed_total == (previous_profile.get("dismissed_count") or 0)):
            logger.info("No new feedback since last distillation — profile is up to date.")
            signals = previous_profile.get("signals", [])
            return {
                "ok": True,
                "reason": "no_new_data",
                "signals": signals,
                "content": render_signals(signals),
            }

    logger.info(
        f"Distilling from {applied_total} applied + {rejected_total} rejected "
        f"+ {dismissed_total} dismissed score factor(s)..."
    )
    prompt = _build_prompt(applied, rejected, applied_total, rejected_total)
    prompt += _build_dismissed_section(dismissed_item_repository.get_recent(50))

    from evaluation.harness import divergence_cases
    divergences = divergence_cases()
    if divergences:
        div_lines = [f"  {d['label']}: {d['title']} @ {d['company']}" for d in divergences[:10]]
        prompt += f"\n\nRANKING DIVERGENCE (high-value signals — model ranking vs user decision):\n" + "\n".join(div_lines)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=CLAUDE_DISTILL_MODEL,
            max_tokens=4000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[_DISTILL_TOOL],
            tool_choice={"type": "tool", "name": "submit_profile"},
        )
    except Exception as e:
        logger.error(f"API error: {e}")
        return {"ok": False, "reason": str(e)}

    from db.repositories.usage_repository import log_anthropic
    log_anthropic(response, "distiller", CLAUDE_DISTILL_MODEL)

    if response.stop_reason == "max_tokens":
        logger.error("Profile output was truncated — not saved.")
        return {"ok": False, "reason": "truncated"}

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        logger.error("No tool_use block in distiller response.")
        return {"ok": False, "reason": "no_tool_block"}

    signals = tool_block.input.get("signals", [])
    if not signals:
        logger.error("Distiller returned empty signals list.")
        return {"ok": False, "reason": "empty_signals"}

    _VALID_TYPES = {"ACCEPT", "REJECT", "INFER", "NEUTRAL"}
    for sig in signals:
        if sig.get("type") not in _VALID_TYPES or not sig.get("dim"):
            logger.error(f"Invalid signal in distiller response: {sig}")
            return {"ok": False, "reason": "invalid_signal", "signal": sig}

    rendered = render_signals(signals)
    preference_repository.save(signals, applied_total, rejected_total, dismissed_total)
    logger.info(f"Preference profile updated ({len(signals)} signals).")
    logger.info(f"Profile:\n{rendered}")

    return {
        "ok": True,
        "signals": signals,
        "content": rendered,
        "applied_count": applied_total,
        "rejected_count": rejected_total,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
    run()
