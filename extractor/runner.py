import json
import logging
import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_EXTRACT_MODEL
from db.repositories import job_repository

logger = logging.getLogger(__name__)

_EXTRACT_TOOL = {
    "name": "submit_structured_data",
    "description": "Submit structured information extracted from a job description.",
    "input_schema": {
        "type": "object",
        "properties": {
            "remote":   {"type": ["boolean", "null"], "description": "Is full remote work available?"},
            "hybrid":   {"type": ["boolean", "null"], "description": "Is hybrid work available?"},
            "seniority": {
                "type": ["string", "null"],
                "enum": ["junior", "mid", "senior", "lead", "director", None],
                "description": "Expected seniority level.",
            },
            "salary_min":      {"type": ["integer", "null"], "description": "Min salary/rate (gross annual or monthly)."},
            "salary_max":      {"type": ["integer", "null"], "description": "Max salary/rate."},
            "salary_currency": {
                "type": ["string", "null"],
                "enum": ["PLN", "EUR", "USD", "GBP", None],
            },
            "stack": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Technologies, frameworks, and tools explicitly mentioned.",
            },
            "company_type": {
                "type": "string",
                "enum": ["startup", "scaleup", "enterprise", "agency", "unknown"],
            },
            "product_vs_outsourcing": {
                "type": "string",
                "enum": ["product", "outsourcing", "mixed", "unknown"],
            },
            "working_language": {
                "type": "string",
                "enum": ["polish", "english", "both", "unknown"],
            },
        },
        "required": [
            "remote", "hybrid", "seniority",
            "salary_min", "salary_max", "salary_currency",
            "stack", "company_type", "product_vs_outsourcing", "working_language",
        ],
    },
}

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def extract_job(description: str) -> dict:
    """Extract structured data from a single job description using Haiku. Returns {} on failure."""
    try:
        response = _get_client().messages.create(
            model=CLAUDE_EXTRACT_MODEL,
            max_tokens=600,
            system=(
                "Extract structured information from the job description. "
                "Use null for fields not explicitly stated — do not infer or assume."
            ),
            messages=[{"role": "user", "content": f"Extract structured data:\n\n{description[:3000]}"}],
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "submit_structured_data"},
        )
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block:
            from db.repositories.usage_repository import log_anthropic
            log_anthropic(response, "extractor", CLAUDE_EXTRACT_MODEL)
            return dict(tool_block.input)
    except Exception as e:
        logger.warning(f"Extraction failed: {e}")
    return {}


def run_extraction(jobs: list[dict]) -> int:
    """Extract structured data for jobs that don't have it yet. Returns count updated."""
    to_extract = [j for j in jobs if j.get("description") and not j.get("structured_data")]
    if not to_extract:
        return 0

    updated = 0
    for job in to_extract:
        data = extract_job(job["description"])
        if data:
            job_repository.update_structured_data(job["id"], data)
            logger.info(f"  Extracted: {job['title']} @ {job['company']} → {json.dumps(data, ensure_ascii=False)[:120]}")
            updated += 1

    return updated
