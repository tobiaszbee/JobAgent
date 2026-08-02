"""Phase 1 of the auto-apply plan: flag jobs the agent would apply to, so the
candidate can validate the selection. Never sends anything — see config.WOULD_APPLY
and evaluation.harness.eval_report()'s "would_apply" gate for the accuracy this is
measured against before any real auto-send is considered."""
from config import WOULD_APPLY


def compute_would_apply(score: float | None, debate_flag: str | None, listwise_rank: int | None = None) -> tuple[bool, str]:
    """Absolute score gate (not a relative top-N cut on its own), so a weak ranking
    run yields zero flagged jobs instead of always flagging "the best of a bad
    batch" — plus a rank_ceiling on the FINAL (post-debate-nudge) listwise_rank, so
    a job whose score alone crosses the floor but whose holistic position is deep in
    the pool doesn't get flagged just because nothing else beat its raw number.
    listwise_rank is required (missing = not flagged), matching this function's
    "only flag with full evidence" stance elsewhere. Computed on final, post-debate
    state, so a dealbreaker_risk flag always suppresses the flag, and any
    overrated/underrated nudge (ranker/debate.py) already moved listwise_rank by
    the time this runs — no second, separate penalty for those flags here."""
    score_floor = WOULD_APPLY["score_floor"]
    rank_ceiling = WOULD_APPLY["rank_ceiling"]
    if (
        score is not None and score >= score_floor
        and debate_flag != "dealbreaker_risk"
        and listwise_rank is not None and listwise_rank <= rank_ceiling
    ):
        return True, f"Score {score:.1f} >= {score_floor:.1f}, rank #{listwise_rank} <= {rank_ceiling}, no dealbreaker risk flagged"
    return False, ""


def compute_revocations(pool_jobs: list[dict], still_flagged_ids: set[str]) -> list[dict]:
    """Jobs currently would_apply=True in the full ranking pool (pool_jobs — every
    'new' job considered this run, would_apply column included) that this run's
    would-apply set (still_flagged_ids) no longer includes — e.g. dropped out of
    the top-N, or a rescore/new debate flag disqualified them. Returns
    {job_id, would_apply, reason} items ready for job_repository.update_would_apply_batch.

    Scoped to pool_jobs only: a job that changed status (applied/rejected) or aged
    out past the ranking pool's own size limit simply isn't in pool_jobs and is left
    untouched here — status changes are handled by their own path, not this one, and
    a job outside the pool was never re-evaluated this run so nothing about it is
    actually known to have changed."""
    return [
        {"job_id": job["id"], "would_apply": False, "reason": "No longer in this run's would-apply set"}
        for job in pool_jobs
        if job.get("would_apply") and job["id"] not in still_flagged_ids
    ]
