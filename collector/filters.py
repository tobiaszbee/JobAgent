import logging
import re

from db.repositories import criteria_repository, job_repository

logger = logging.getLogger(__name__)


def _contains_keyword(text: str, keyword: str) -> bool:
    # Explicit non-alphanumeric lookaround rather than \b: \b only fires
    # between a \w char and a non-\w char, so a keyword ending in a symbol
    # (c++, c#, .net) followed by whitespace has non-word characters on both
    # sides of the trailing \b and would never match.
    pattern = rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])"
    return re.search(pattern, text) is not None


def title_banned_reason(title: str, rejected_kw: list[str]) -> str | None:
    # Used to skip the description fetch entirely for jobs already guaranteed
    # to be auto-rejected; required-keyword checks need the full text and
    # stay in apply_keyword_filter().
    text = title.lower()
    for kw in rejected_kw:
        if _contains_keyword(text, kw):
            return f"Auto-rejected: contains '{kw}'"
    return None


def apply_keyword_filter(jobs: list[dict] | None = None) -> dict:
    # Hard-rejects on two checks: any banned keyword present, or no required
    # keyword present at all. `jobs` lets a caller also running
    # apply_language_filter() share one get_new() fetch instead of each
    # pulling its own.
    rejected_kw = [r.lower() for r in criteria_repository.get_active("rejected")]
    required_kw = [r.lower() for r in criteria_repository.get_active("required")]

    if not rejected_kw and not required_kw:
        return {"checked": 0, "auto_rejected": 0, "rejected_ids": []}

    if jobs is None:
        jobs = job_repository.get_new()
    auto_rejected = 0
    rejected_ids = []

    for job in jobs:
        text = f"{job['title']} {job.get('description') or ''}".lower()
        reason = None

        for kw in rejected_kw:
            if _contains_keyword(text, kw):
                reason = f"Auto-rejected: contains '{kw}'"
                break

        if not reason and required_kw and not any(_contains_keyword(text, kw) for kw in required_kw):
            reason = f"Auto-rejected: missing required keyword ({', '.join(required_kw)})"

        if reason:
            job_repository.update_score_and_status(job["id"], 0.0, reason, "auto_rejected")
            auto_rejected += 1
            rejected_ids.append(job["id"])
            logger.info(f"  [E2] {job['title']} @ {job['company']}, {reason}")

    return {"checked": len(jobs), "auto_rejected": auto_rejected, "rejected_ids": rejected_ids}
