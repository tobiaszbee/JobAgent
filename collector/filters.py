import logging

from db.repositories import criteria_repository, job_repository

logger = logging.getLogger(__name__)


def apply_keyword_filter() -> dict:
    """Hard-reject jobs based on two checks (in order):
    1. Banned keywords (rejected): any match in title+description → reject.
    2. Required keywords: none present anywhere in title+description → reject.
    """
    rejected_kw = [r.lower() for r in criteria_repository.get_active("rejected")]
    required_kw = [r.lower() for r in criteria_repository.get_active("required")]

    if not rejected_kw and not required_kw:
        return {"checked": 0, "auto_rejected": 0}

    jobs = job_repository.get_new()
    auto_rejected = 0

    for job in jobs:
        text = f"{job['title']} {job.get('description') or ''}".lower()
        reason = None

        for kw in rejected_kw:
            if kw in text:
                reason = f"Auto-rejected: contains '{kw}'"
                break

        if not reason and required_kw and not any(kw in text for kw in required_kw):
            reason = f"Auto-rejected: missing required keyword ({', '.join(required_kw)})"

        if reason:
            job_repository.update_score_and_status(job["id"], 0.0, reason, "auto_rejected")
            auto_rejected += 1
            logger.info(f"  [E2] {job['title']} @ {job['company']} — {reason}")

    return {"checked": len(jobs), "auto_rejected": auto_rejected}
