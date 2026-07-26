"""Phase 1 of the auto-apply plan: flag jobs the agent would apply to, so the
candidate can validate the selection. Never sends anything — see config.WOULD_APPLY
and evaluation.harness.eval_report()'s "would_apply" gate for the accuracy this is
measured against before any real auto-send is considered."""
from config import WOULD_APPLY


def compute_would_apply(score: float | None, debate_flag: str | None) -> tuple[bool, str]:
    """Absolute score gate (not a relative top-N cut), so a weak ranking run yields
    zero flagged jobs instead of always flagging "the best of a bad batch". Computed
    on final, post-debate state so a dealbreaker_risk flag always suppresses the flag."""
    score_floor = WOULD_APPLY["score_floor"]
    if score is not None and score >= score_floor and debate_flag != "dealbreaker_risk":
        return True, f"Score {score:.1f} >= {score_floor:.1f}, no dealbreaker risk flagged"
    return False, ""
