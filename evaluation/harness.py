import api_client
from config import WOULD_APPLY


def eval_report() -> dict:
    """Full evaluation report: apply-rate per rank bucket (the ranking quality
    signal, precision@K is still included for backward compat but is stale,
    see routers/evaluation.py), divergence cases, and the would-apply flag's
    precision. Computed server-side by JobAgentWeb (routers/evaluation.py)
    against the shared, canonical ranking data, this just proxies it instead of
    re-deriving the same numbers from a second, independently-fetched copy of the
    ranked jobs, which is exactly how the two implementations drifted out of sync
    before (the "reviewed"-exclusion fix had to be applied by hand in both repos)."""
    report = api_client.get("/api/eval/report").json()
    # JobAgentWeb's copy of this value is display-only, for callers that hit its
    # API directly, JobAgent is the actual source of truth since it's the one
    # that enforces this floor (ranker/would_apply.py), so override rather than
    # trust JobAgentWeb's mirror to have been kept in sync.
    report["would_apply_score_floor"] = WOULD_APPLY["score_floor"]
    return report


def divergence_cases() -> list[dict]:
    """Used directly by evaluator/runner.py and preference_agent/runner.py for
    calibration feedback, pulled out of the full report rather than duplicating
    its computation."""
    return eval_report()["divergence_cases"]
