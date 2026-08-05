# Phase 1 of the auto-apply plan: flag jobs the agent would apply to, so the
# candidate can validate the selection. Never sends anything, see
# config.WOULD_APPLY and evaluation.harness.eval_report()'s "would_apply"
# gate for the accuracy this is measured against.
from config import WOULD_APPLY


def compute_would_apply(score: float | None, debate_flag: str | None, listwise_rank: int | None = None) -> tuple[bool, str]:
    # Absolute score gate, not a relative top-N cut, so a weak ranking run
    # yields zero flagged jobs instead of flagging "the best of a bad batch".
    # rank_ceiling applies to the final post-debate-nudge listwise_rank, so a
    # job whose score alone crosses the floor but sits deep in the pool
    # doesn't get flagged. listwise_rank is required, missing means not
    # flagged.
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
    # Jobs currently would_apply=True in pool_jobs that this run's
    # still_flagged_ids no longer includes (dropped out of the top-N, or a
    # rescore/new debate flag disqualified them). Scoped to pool_jobs only: a
    # job that changed status or aged out of the ranking pool simply isn't in
    # pool_jobs and is left untouched, since it was never re-evaluated this run.
    return [
        {"job_id": job["id"], "would_apply": False, "reason": "No longer in this run's would-apply set"}
        for job in pool_jobs
        if job.get("would_apply") and job["id"] not in still_flagged_ids
    ]
