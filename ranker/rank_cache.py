"""Skip re-running listwise+debate ranking when the candidate pool hasn't
changed since the last run — Opus + debate calls are the expensive, repeated
(not growing) cost in the daily ranking pipeline (see scripts/rank_jobs.py)."""


def reuse_if_unchanged(listwise_pool: list[dict], previously_fetched_jobs: list[dict]) -> list[dict] | None:
    """Returns the previous run's ranked jobs (sorted by listwise_rank) if the
    exact same set of job IDs was already ranked last run, else None — meaning
    the caller should re-run listwise_rank + debate_rank."""
    if not listwise_pool:
        return []
    current_ids = {j["id"] for j in listwise_pool}
    previous_ids = {j["id"] for j in previously_fetched_jobs if j.get("listwise_rank") is not None}
    if current_ids != previous_ids:
        return None
    return sorted(listwise_pool, key=lambda j: j["listwise_rank"])
