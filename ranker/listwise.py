import json
import logging
import re
import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_RANK_MODEL
from collector.utils import build_excerpt

logger = logging.getLogger(__name__)

_RANKING_TOOL = {
    "name": "submit_ranking",
    "description": "Submit the final ranked list of jobs from best to worst fit for the candidate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ranking": {
                "type": "array",
                "description": "All jobs ordered from best (index 0) to worst fit.",
                "items": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "reason": {"type": "string", "description": "One sentence: key reason for this position."},
                    },
                    "required": ["job_id", "reason"],
                },
            },
            "summary": {"type": "string", "description": "2-3 sentence overall analysis of this job batch."},
        },
        "required": ["ranking"],
    },
}


def _format_job(job: dict, position: int) -> str:
    structured = {}
    raw = job.get("structured_data")
    if raw:
        try:
            structured = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass

    parts = [f"[Job #{position + 1} | ID: {job['id']}]"]
    parts.append(f"Title: {job['title']} @ {job['company']}")
    if job.get("location"):
        parts.append(f"Location: {job['location']}")

    if structured:
        tags = []
        if structured.get("remote"):
            tags.append("remote")
        elif structured.get("hybrid"):
            tags.append("hybrid")
        if structured.get("seniority"):
            tags.append(structured["seniority"])
        if structured.get("salary_min") and structured.get("salary_max"):
            period = structured.get("salary_period")
            period_suffix = f"/{period}" if period else ""
            tags.append(f"{structured['salary_min']}-{structured['salary_max']} {structured.get('salary_currency', '')}{period_suffix}")
        if structured.get("company_type") and structured["company_type"] != "unknown":
            tags.append(structured["company_type"])
        if structured.get("product_vs_outsourcing") and structured["product_vs_outsourcing"] != "unknown":
            tags.append(structured["product_vs_outsourcing"])
        if structured.get("stack"):
            tags.append(", ".join(structured["stack"][:5]))
        if tags:
            parts.append(f"Tags: {' | '.join(tags)}")

    desc = build_excerpt(job.get("description"), job.get("source")).replace("\n", " ")
    parts.append(f"Description: {desc}")
    return "\n".join(parts)


def _parse_ranking_json(text: str) -> list[dict]:
    m = re.search(r"<ranking>(.*?)</ranking>", text, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return []


def listwise_rank(jobs: list[dict], candidate_profile: str, preferences: list[dict]) -> list[dict]:
    """Extended thinking is incompatible with forced tool_choice, so we use JSON in text instead."""
    if not jobs:
        return []

    from preference_agent.profile import render_signals
    prefs_text = ""
    if preferences:
        scored = [s for s in preferences if s.get("type") != "NEUTRAL"]
        if scored:
            prefs_text = f"PREFERENCE PROFILE:\n{render_signals(scored)}\n\n"

    jobs_text = "\n\n---\n\n".join(_format_job(job, i) for i, job in enumerate(jobs))

    system = f"""You are ranking job listings for a candidate. Analyze every job carefully and produce a definitive ranking.

{candidate_profile}

{prefs_text}Your task: rank ALL {len(jobs)} jobs from best (rank 1) to worst fit. Consider:
- Overall match with candidate profile and experience
- Preference signals (strong signals = heavy weight)
- Role quality, growth potential, company type
- Dealbreakers (REJECT[conf=ABSOLUTE/HIGH] signals)

Every job must appear exactly once in the ranking.

Do all your reordering and self-correction before you start writing the JSON — once you begin the <ranking> block, each "reason" must already be your settled, final answer for that job. Never write deliberation, corrections, or meta-commentary about the ranking process itself (e.g. "wait, correcting...", "actually X is better", "placing here by ID") into a "reason" value — it is shown directly to the candidate and must read as a clean, final one-sentence explanation of that job's fit.

After your analysis, output ONLY the final ranking as a JSON array inside <ranking> tags, like this:
<ranking>
[
  {{"job_id": "abc123", "reason": "Best match: senior Python role at product company, remote"}},
  {{"job_id": "def456", "reason": "Good but agency work"}}
]
</ranking>

Include ALL {len(jobs)} jobs. No text after the closing </ranking> tag."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=CLAUDE_RANK_MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            messages=[{"role": "user", "content": f"Rank these {len(jobs)} jobs from best to worst:\n\n{jobs_text}"}],
        )
    except Exception as e:
        logger.error(f"Listwise ranking failed: {e}")
        return [{**job, "listwise_rank": i + 1, "rank_reason": ""} for i, job in enumerate(jobs)]

    from db.repositories.usage_repository import log_anthropic
    log_anthropic(response, "ranker", CLAUDE_RANK_MODEL)

    text_block = next((b for b in response.content if b.type == "text"), None)
    if not text_block:
        logger.error("No text block in Opus listwise response")
        return [{**job, "listwise_rank": i + 1, "rank_reason": ""} for i, job in enumerate(jobs)]

    try:
        ranking = _parse_ranking_json(text_block.text)
    except Exception as e:
        logger.error(f"Failed to parse ranking JSON: {e}\nResponse: {text_block.text[:500]}")
        return [{**job, "listwise_rank": i + 1, "rank_reason": ""} for i, job in enumerate(jobs)]

    job_by_id = {job["id"]: job for job in jobs}
    result = []
    seen = set()

    for rank_pos, item in enumerate(ranking, 1):
        job_id = item.get("job_id")
        if job_id in job_by_id and job_id not in seen:
            result.append({**job_by_id[job_id], "listwise_rank": rank_pos, "rank_reason": item.get("reason", "")})
            seen.add(job_id)

    # Safety net: add any jobs Opus missed
    for job in jobs:
        if job["id"] not in seen:
            result.append({**job, "listwise_rank": len(result) + 1, "rank_reason": ""})

    logger.info(f"Listwise ranking complete: {len(result)} jobs ranked")
    return result
