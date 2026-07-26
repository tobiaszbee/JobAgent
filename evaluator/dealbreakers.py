import json
import logging

from db.repositories import candidate_preferences_repository, job_repository

logger = logging.getLogger(__name__)


def _structured_data(job: dict) -> dict:
    raw = job.get("structured_data")
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}


# Standard full-time B2B assumption for converting an hourly rate to its annual
# equivalent: 168 hours/month (21 working days x 8h) x 12 months.
_HOURS_PER_YEAR = 168 * 12
_MONTHS_PER_YEAR = 12


def _annualize(amount: int, period: str | None) -> int | None:
    """Convert a salary/rate to its annual-gross equivalent. The candidate's own
    salary_min (questionnaire) is always annual, so job pay must be normalized to
    the same basis before comparing — comparing e.g. a "100-145 PLN/hour" B2B rate
    directly against an annual floor is the bug this fixes. Returns None (skip,
    don't guess) when the period is unknown."""
    if period == "yearly":
        return amount
    if period == "monthly":
        return amount * _MONTHS_PER_YEAR
    if period == "hourly":
        return amount * _HOURS_PER_YEAR
    return None


def _salary_floor_reason(job_structured: dict, salary_min: int | None, salary_currency: str | None) -> str | None:
    if not salary_min:
        return None
    job_max = job_structured.get("salary_max")
    job_currency = job_structured.get("salary_currency")
    if not job_max or not job_currency or not salary_currency:
        return None
    if job_currency != salary_currency:
        return None  # no FX conversion in this pass — skip rather than guess
    annual_job_max = _annualize(job_max, job_structured.get("salary_period"))
    if annual_job_max is None:
        return None  # unknown pay period — never guess a basis, skip rather than false-reject
    if annual_job_max < salary_min:
        period = job_structured.get("salary_period")
        return (
            f"Dealbreaker: salary_max {job_max} {job_currency}/{period} "
            f"(~{annual_job_max} {job_currency}/year) below your minimum {salary_min} {salary_currency}/year"
        )
    return None


def _remote_only_reason(job_structured: dict, work_mode: list[str]) -> str | None:
    if work_mode != ["remote"]:
        return None
    remote = job_structured.get("remote")
    hybrid = job_structured.get("hybrid")
    if remote is None and hybrid is None:
        return None  # no data — never treat absence as a violation
    # hybrid=True always disqualifies a remote-only candidate, even if remote=True is
    # also set on the same posting — confirmed with the candidate directly: hybrid
    # means occasional required office days, which breaks a remote-only requirement
    # regardless of whether the posting also advertises a remote option/policy.
    if hybrid is True or remote is False:
        return "Dealbreaker: requires on-site/hybrid presence, but you selected remote-only"
    return None


def apply_dealbreaker_filter(jobs: list[dict]) -> tuple[list[dict], dict]:
    """Deterministic, pre-LLM hard filter. Runs on a list of not-yet-scored jobs
    (typically evaluator/runner.py's unscored_jobs) and auto-rejects any that violate
    a structured-field dealbreaker from the candidate's questionnaire — zero LLM cost
    for the jobs it catches. Returns (surviving_jobs, {checked, auto_rejected})."""
    prefs = candidate_preferences_repository.get_active()
    if not prefs:
        return jobs, {"checked": len(jobs), "auto_rejected": 0}

    salary_min = prefs.get("salary_min")
    salary_currency = prefs.get("salary_currency")
    work_mode = prefs.get("work_mode") or []

    if not salary_min and work_mode != ["remote"]:
        return jobs, {"checked": len(jobs), "auto_rejected": 0}

    surviving = []
    auto_rejected = 0

    for job in jobs:
        structured = _structured_data(job)
        reason = _salary_floor_reason(structured, salary_min, salary_currency)
        if not reason:
            reason = _remote_only_reason(structured, work_mode)

        if reason:
            job_repository.update_score_and_status(job["id"], 0.0, reason, "auto_rejected")
            auto_rejected += 1
            logger.info(f"  [dealbreaker] {job['title']} @ {job['company']} — {reason}")
        else:
            surviving.append(job)

    return surviving, {"checked": len(jobs), "auto_rejected": auto_rejected}
