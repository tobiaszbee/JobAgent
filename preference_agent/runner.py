import sys

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from db.migrations import init_db
from db.repositories import job_repository, preference_repository

_SYSTEM = """\
You distill job application history into a dense preference profile consumed by another AI evaluator.
Optimize for: maximum information density, unambiguous signals, evidence-backed confidence.

SCOPE — analyze ONLY these dimensions:
- Compensation/rate patterns (explicit amounts, "competitive" language, missing rate)
- Company type (product vs agency/staffing/outsourcing vs enterprise)
- Contract form (B2B, employment, contract-to-hire)
- Work culture signals (async, startup pace, corporate, team size)

EXCLUDED — do NOT include (handled by hardcoded rules):
- Location, remote/on-site, geography, visa, language

OUTPUT FORMAT (strict):
ACCEPT[dim=value; conf=LEVEL; n=X/Y]: optional user-facing note
REJECT[dim=value; conf=LEVEL; n=X/Y]: include user reason if available
INFER[inference; from=N examples]: derived pattern not directly stated
NEUTRAL[dim; no_signal]: dimension with no clear preference pattern

LEVEL values: ABSOLUTE(100% consistent), HIGH(>80%), MEDIUM(60-80%), LOW(<60%)
X/Y = count matching this signal / total jobs in that class

Rules:
- One signal per line, no headers, no prose, no explanation
- Infer dealbreakers from consistent rejections + repeated user reasons
- INFER entries for patterns where cause is implicit (e.g. min rate derived from rejection reasons)
- If a dimension shows no pattern, emit NEUTRAL — do not omit it
- Output ONLY the profile lines, nothing else\
"""


def _job_line(job: dict, include_reason: bool = False) -> str:
    title = job.get("title", "?")
    company = job.get("company", "?")
    loc = job.get("location", "")
    desc = (job.get("description") or "").replace("\n", " ")[:180].strip()
    parts = [f'"{title}" @ {company}']
    if loc:
        parts.append(f"[{loc}]")
    if desc:
        parts.append(f"| {desc}")
    if include_reason:
        reason = (job.get("rejection_reason") or job.get("score_reason") or "").strip()
        if reason:
            parts.append(f"| reason: {reason[:120]}")
    return " ".join(parts)


def _build_prompt(
    applied: list[dict],
    rejected: list[dict],
    existing_profile: str = "",
) -> str:
    sections = []

    if applied:
        lines = [f"APPLIED ({len(applied)} jobs):"]
        for j in applied:
            lines.append(f"  {_job_line(j)}")
        sections.append("\n".join(lines))
    else:
        sections.append("APPLIED (0 jobs): none yet")

    if rejected:
        lines = [f"REJECTED ({len(rejected)} jobs):"]
        for j in rejected:
            lines.append(f"  {_job_line(j, include_reason=True)}")
        sections.append("\n".join(lines))
    else:
        sections.append("REJECTED (0 jobs): none yet")

    ref = existing_profile.strip() if existing_profile else "none"
    sections.append(f"PREVIOUS PROFILE (reference only — regenerate from scratch):\n{ref}")

    return "\n\n".join(sections)


def run(log=print) -> dict:
    init_db()

    applied, rejected = job_repository.get_all_feedback()
    log(f"Distilling preferences from {len(applied)} applied + {len(rejected)} rejected jobs...")

    if not applied and not rejected:
        log("No feedback data yet — apply or reject some jobs first.")
        return {"ok": False, "reason": "no_data"}

    existing = preference_repository.get_latest()
    existing_content = existing["content"] if existing else ""

    prompt = _build_prompt(applied, rejected, existing_content)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        log(f"API error: {e}")
        return {"ok": False, "reason": str(e)}

    content = response.content[0].text.strip()
    preference_repository.save(content, len(applied), len(rejected))
    log(f"Preference profile updated ({len(content)} chars).")
    log(f"Profile:\n{content}")

    return {
        "ok": True,
        "content": content,
        "applied_count": len(applied),
        "rejected_count": len(rejected),
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    run()
