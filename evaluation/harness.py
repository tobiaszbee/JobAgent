import api_client
from config import WOULD_APPLY


def eval_report() -> dict:
    # Computed server-side by JobAgentWeb (routers/evaluation.py) against the
    # shared, canonical ranking data; this just proxies it instead of
    # re-deriving the same numbers from a second, independently-fetched copy.
    report = api_client.get("/api/eval/report").json()
    # JobAgent is the actual source of truth for this floor (ranker/would_apply.py
    # enforces it), so override rather than trust JobAgentWeb's display-only mirror.
    report["would_apply_score_floor"] = WOULD_APPLY["score_floor"]
    return report


def divergence_cases() -> list[dict]:
    return eval_report()["divergence_cases"]
