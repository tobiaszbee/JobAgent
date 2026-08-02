import logging
import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from db.repositories.usage_repository import log_anthropic

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


_SUGGEST_TOOL = {
    "name": "submit_query_suggestions",
    "description": "Submit suggested LinkedIn search queries based on the user's application history.",
    "input_schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Suggested search query strings (job titles, role names, specializations).",
            },
            "rationale": {
                "type": "string",
                "description": "Brief explanation of the suggestions.",
            },
        },
        "required": ["queries", "rationale"],
    },
}


def suggest_queries() -> dict:
    from db.repositories import job_repository, criteria_repository

    applied, _ = job_repository.get_all_feedback()
    if len(applied) < 3:
        return {
            "ok": False,
            "reason": "Need at least 3 applied jobs for meaningful suggestions.",
            "queries": [],
            "rationale": "",
        }

    existing = criteria_repository.get_active("search_query")
    jobs_text = "\n".join(f"- {j['title']} @ {j['company']}" for j in applied[:30])
    existing_text = ", ".join(f'"{q}"' for q in existing) if existing else "none"

    prompt = f"""The candidate has applied to these jobs:
{jobs_text}

Search queries already in use: {existing_text}

Suggest 5-10 new LinkedIn search queries that would surface similar jobs the candidate hasn't found yet.
Focus on:
- Alternative job title variations and synonyms visible in the applied jobs
- More specific specializations or sub-roles
- Stack-specific searches if a clear technology pattern is visible
- Related roles the candidate might not have considered

Do NOT suggest queries already in use. Return concise, LinkedIn-friendly search strings."""

    try:
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
            tools=[_SUGGEST_TOOL],
            tool_choice={"type": "tool", "name": "submit_query_suggestions"},
        )
    except Exception as e:
        logger.error(f"Query expansion failed: {e}")
        return {"ok": False, "reason": str(e), "queries": [], "rationale": ""}

    log_anthropic(response, "query_expansion", CLAUDE_MODEL)

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        return {"ok": False, "reason": "No response from model", "queries": [], "rationale": ""}

    return {
        "ok": True,
        "queries": tool_block.input.get("queries", []),
        "rationale": tool_block.input.get("rationale", ""),
    }
