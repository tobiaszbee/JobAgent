import json
import logging
import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from collector.utils import build_excerpt

logger = logging.getLogger(__name__)

_VALID_FLAGS = {"dealbreaker_risk", "overrated", "underrated"}

_DEBATE_TOOL = {
    "name": "submit_debate_review",
    "description": "Submit a second-opinion critique of an existing job ranking.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "description": "One entry per job that you want to flag — omit jobs you have no concern about.",
                "items": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "flag": {
                            "type": "string",
                            "enum": sorted(_VALID_FLAGS),
                            "description": (
                                "dealbreaker_risk: the primary ranking likely missed a real dealbreaker "
                                "(e.g. stack similarity masking a mismatch on seniority, company type, or "
                                "an explicit requirement the candidate can't meet). "
                                "overrated: ranked too high for a softer reason. "
                                "underrated: ranked too low — this job deserves more credit."
                            ),
                        },
                        "note": {"type": "string", "description": "One sentence explaining the flag."},
                    },
                    "required": ["job_id", "flag", "note"],
                },
            },
        },
        "required": ["reviews"],
    },
}


def _format_job_for_review(job: dict, position: int) -> str:
    parts = [f"[Rank #{position + 1} | ID: {job['id']}]"]
    parts.append(f"Title: {job['title']} @ {job['company']}")
    reason = job.get("rank_reason") or ""
    if reason:
        parts.append(f"Primary ranking's reason: {reason}")

    breakdown = job.get("score_breakdown")
    if breakdown:
        try:
            b = json.loads(breakdown) if isinstance(breakdown, str) else breakdown
        except Exception:
            b = None
        if b:
            if b.get("pros"):
                parts.append(f"Pros: {'; '.join(b['pros'])}")
            if b.get("cons"):
                parts.append(f"Cons: {'; '.join(b['cons'])}")

    desc = build_excerpt(job.get("description"), job.get("source")).replace("\n", " ")
    parts.append(f"Description: {desc}")
    return "\n".join(parts)


def _parse_reviews(tool_input: dict) -> dict[str, dict]:
    reviews = {}
    for item in tool_input.get("reviews", []):
        job_id = item.get("job_id")
        flag = item.get("flag")
        if job_id and flag in _VALID_FLAGS:
            reviews[job_id] = {"flag": flag, "note": item.get("note", "")}
    return reviews


def debate_rank(ranked_jobs: list[dict], candidate_profile: str) -> list[dict]:
    """Second-opinion critique of an already-ranked shortlist (the listwise top-N),
    using a different model than the primary ranker. Does not re-derive the ranking
    from scratch — only flags disagreements. Jobs flagged "dealbreaker_risk" are
    demoted to the bottom of the list; other flags are attached but don't reorder."""
    if not ranked_jobs:
        return ranked_jobs

    jobs_text = "\n\n---\n\n".join(_format_job_for_review(job, i) for i, job in enumerate(ranked_jobs))

    system = f"""You are a second, independent reviewer checking another model's job ranking for this candidate.

{candidate_profile}

The primary ranking below is already ordered best (rank #1) to worst. Your job is NOT to re-rank —
it's to catch cases the primary ranking may have gotten wrong, especially where strong stack/keyword
similarity could mask a real dealbreaker (seniority mismatch, wrong company type, an explicit
requirement the candidate can't meet, etc.).

Only flag jobs you genuinely disagree with. Most jobs need no flag at all — do not flag a job just
to have something to say about it.

Use the submit_debate_review tool to report your findings."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": f"Review this ranking of {len(ranked_jobs)} jobs:\n\n{jobs_text}"}],
            tools=[_DEBATE_TOOL],
            tool_choice={"type": "tool", "name": "submit_debate_review"},
        )
    except Exception as e:
        logger.error(f"Debate review failed: {e}")
        return ranked_jobs

    from db.repositories.usage_repository import log_anthropic
    log_anthropic(response, "debate", CLAUDE_MODEL)

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        logger.error("No tool_use block in debate response")
        return ranked_jobs

    reviews = _parse_reviews(tool_block.input)
    if not reviews:
        return ranked_jobs

    demoted = []
    kept = []
    for job in ranked_jobs:
        review = reviews.get(job["id"])
        if review:
            job = {**job, "debate_flag": review["flag"], "debate_note": review["note"]}
        if review and review["flag"] == "dealbreaker_risk":
            demoted.append(job)
        else:
            kept.append(job)

    reordered = kept + demoted
    for i, job in enumerate(reordered, 1):
        job["listwise_rank"] = i

    if demoted:
        logger.info(f"Debate review: demoted {len(demoted)} job(s) flagged dealbreaker_risk")

    return reordered
