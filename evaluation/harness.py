import api_client


def eval_report() -> dict:
    """Full evaluation report: precision@K, divergence cases, and the would-apply
    flag's precision. Computed server-side by JobAgentWeb (routers/evaluation.py)
    against the shared, canonical ranking data — this just proxies it instead of
    re-deriving the same numbers from a second, independently-fetched copy of the
    ranked jobs, which is exactly how the two implementations drifted out of sync
    before (the "reviewed"-exclusion fix had to be applied by hand in both repos)."""
    return api_client.get("/api/eval/report").json()


def divergence_cases() -> list[dict]:
    """Used directly by evaluator/runner.py and preference_agent/runner.py for
    calibration feedback, pulled out of the full report rather than duplicating
    its computation."""
    return eval_report()["divergence_cases"]
