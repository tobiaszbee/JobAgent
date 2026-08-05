"""Skip re-running listwise+debate ranking when the candidate pool hasn't
changed since the last run, Opus + debate calls are the expensive, repeated
(not growing) cost in the daily ranking pipeline (see scripts/rank_jobs.py)."""
from ranker.debate import DEBATE_UNAVAILABLE_FLAG
from ranker.listwise import FALLBACK_RANK_REASON


def _is_degraded(job: dict) -> bool:
    """True if this job's stored ranking is a failure fallback, not a genuine
    listwise/debate result, reusing it would silently perpetuate whatever
    outage produced it for as long as the candidate pool happens to stay the
    same, with no retry and nothing visibly wrong."""
    return job.get("rank_reason") == FALLBACK_RANK_REASON or job.get("debate_flag") == DEBATE_UNAVAILABLE_FLAG


def reuse_if_unchanged(listwise_pool: list[dict], previously_fetched_jobs: list[dict]) -> list[dict] | None:
    """Returns the previous run's ranked jobs (sorted by listwise_rank) if the
    exact same set of job IDs was already ranked last run AND that previous
    result was a genuine listwise/debate outcome, else None, meaning the
    caller should re-run listwise_rank + debate_rank."""
    if not listwise_pool:
        return []
    previous_ranked = [j for j in previously_fetched_jobs if j.get("listwise_rank") is not None]
    current_ids = {j["id"] for j in listwise_pool}
    previous_ids = {j["id"] for j in previous_ranked}
    if current_ids != previous_ids:
        return None
    if any(_is_degraded(j) for j in previous_ranked):
        return None
    return sorted(listwise_pool, key=lambda j: j["listwise_rank"])
