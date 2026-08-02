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


# Static, approximate mid-rates to PLN — not live-fetched. A dealbreaker filter
# only needs to be directionally right ("is this roughly in range"), not payroll-
# accurate; update these occasionally rather than wiring in a live FX API for a
# threshold check. Previously a currency mismatch just skipped the check
# entirely rather than applying it conservatively, silently letting e.g. every
# EUR/USD posting bypass a PLN salary floor regardless of actual pay.
_TO_PLN_RATE = {"PLN": 1.0, "EUR": 4.3, "USD": 4.0, "GBP": 5.0}


def _to_pln(amount: int, currency: str | None) -> int | None:
    rate = _TO_PLN_RATE.get(currency)
    return round(amount * rate) if rate is not None else None


def _salary_floor_reason(job_structured: dict, salary_min: int | None, salary_currency: str | None) -> str | None:
    if not salary_min:
        return None
    job_max = job_structured.get("salary_max")
    job_currency = job_structured.get("salary_currency")
    if not job_max or not job_currency or not salary_currency:
        return None
    annual_job_max = _annualize(job_max, job_structured.get("salary_period"))
    if annual_job_max is None:
        return None  # unknown pay period — never guess a basis, skip rather than false-reject

    # Always compare in PLN, even when both currencies already match (rate=1.0,
    # a no-op) — one path instead of a same-currency/converted branch split.
    job_max_pln = _to_pln(annual_job_max, job_currency)
    candidate_min_pln = _to_pln(salary_min, salary_currency)
    if job_max_pln is None or candidate_min_pln is None:
        return None  # unsupported currency — skip rather than guess

    if job_max_pln < candidate_min_pln:
        period = job_structured.get("salary_period")
        conversion_note = "" if job_currency == "PLN" else f" (~{job_max_pln} PLN)"
        return (
            f"Dealbreaker: salary_max {job_max} {job_currency}/{period} "
            f"(~{annual_job_max} {job_currency}/year{conversion_note}) below your minimum {salary_min} {salary_currency}/year"
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


def _geo_reason(job_structured: dict, work_mode: list[str], remote_countries: list[str]) -> str | None:
    """Closes the geo hole: a job can be genuinely remote (passes _remote_only_reason)
    but still restricted to countries that don't include the candidate's — e.g.
    "Remote — US only" reaching a candidate in Poland, with nothing anywhere in the
    pipeline able to catch it (see extractor/runner.py's remote_regions field).

    Deliberately conservative: any missing/unclear signal skips the check rather
    than rejecting. remote_regions is a brand-new field (added alongside this
    dealbreaker) — every job extracted before today has no such key at all, and
    an empty list explicitly means "unstated" per its own schema description, not
    "no countries allowed". Both cases must resolve to "don't reject" for this to
    be safe to enable against the existing, unbackfilled pool."""
    if "remote" not in work_mode:
        return None
    if not remote_countries:
        return None  # candidate didn't say which countries matter — nothing to check
    if job_structured.get("remote") is not True:
        return None  # not a remote posting at all — a different dealbreaker's job
    job_regions = job_structured.get("remote_regions")
    if not job_regions:
        return None  # unstated (or pre-migration row) — never treat as a restriction

    from collector.location import location_matches
    # Trailing space lets a bare "EU" match location.py's "eu " Europe token the
    # same way real free-text job locations do — this list is otherwise just
    # joined country/region names, not a sentence.
    job_location_text = ", ".join(job_regions) + " "
    if any(location_matches(job_location_text, country) for country in remote_countries):
        return None
    return (
        f"Dealbreaker: remote work restricted to {', '.join(job_regions)}, "
        f"not available for your selected countries ({', '.join(remote_countries)})"
    )


def _seniority_reason(job_structured: dict, seniority_levels: list[str]) -> str | None:
    """Candidate-side and job-side seniority data both already existed (questionnaire's
    seniority_levels, extraction's seniority) with nothing enforcing a hard mismatch —
    a near-free addition compared to the geo/currency checks above."""
    if not seniority_levels:
        return None  # candidate didn't restrict — nothing to check
    job_seniority = job_structured.get("seniority")
    if not job_seniority:
        return None  # unknown — never treat absence as a violation
    if job_seniority in seniority_levels:
        return None
    return (
        f"Dealbreaker: seniority level '{job_seniority}' not in your selected levels "
        f"({', '.join(seniority_levels)})"
    )


def _no_salary_disclosed_reason(job_structured: dict, show_jobs_without_salary: bool) -> str | None:
    """The questionnaire checkbox ("Also show postings with no salary listed",
    checked/True by default) was saved but never read anywhere — unchecking it
    had no effect at all. Only ever filters when the candidate explicitly opted
    out; a job that does disclose a salary is never touched by this check."""
    if show_jobs_without_salary:
        return None
    if job_structured.get("salary_max") or job_structured.get("salary_min"):
        return None  # salary IS disclosed — not this check's concern
    return "Dealbreaker: no salary disclosed, and you chose to hide postings without salary listed"


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
    remote_countries = prefs.get("remote_countries") or []
    seniority_levels = prefs.get("seniority_levels") or []
    # Unset (predates this field) defaults to True, matching the questionnaire
    # checkbox's own default (checked) — never surprise an existing candidate
    # with newly-hidden postings just because this key doesn't exist yet.
    raw_show_no_salary = prefs.get("show_jobs_without_salary")
    show_jobs_without_salary = True if raw_show_no_salary is None else bool(raw_show_no_salary)

    if (
        not salary_min and "remote" not in work_mode and not seniority_levels
        and show_jobs_without_salary
    ):
        return jobs, {"checked": len(jobs), "auto_rejected": 0}

    surviving = []
    auto_rejected = 0

    for job in jobs:
        structured = _structured_data(job)
        reason = _salary_floor_reason(structured, salary_min, salary_currency)
        if not reason:
            reason = _remote_only_reason(structured, work_mode)
        if not reason:
            reason = _geo_reason(structured, work_mode, remote_countries)
        if not reason:
            reason = _seniority_reason(structured, seniority_levels)
        if not reason:
            reason = _no_salary_disclosed_reason(structured, show_jobs_without_salary)

        if reason:
            job_repository.update_score_and_status(job["id"], 0.0, reason, "auto_rejected")
            auto_rejected += 1
            logger.info(f"  [dealbreaker] {job['title']} @ {job['company']} — {reason}")
        else:
            surviving.append(job)

    return surviving, {"checked": len(jobs), "auto_rejected": auto_rejected}
