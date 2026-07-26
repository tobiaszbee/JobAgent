from unittest.mock import patch

from ranker.would_apply import compute_would_apply


@patch("ranker.would_apply.WOULD_APPLY", {"score_floor": 7.0})
class TestComputeWouldApply:
    def test_flags_job_at_or_above_floor(self):
        flagged, reason = compute_would_apply(7.0, None)
        assert flagged is True
        assert "7.0" in reason

    def test_flags_job_above_floor(self):
        flagged, reason = compute_would_apply(9.0, None)
        assert flagged is True

    def test_does_not_flag_job_below_floor(self):
        flagged, reason = compute_would_apply(6.9, None)
        assert flagged is False
        assert reason == ""

    def test_does_not_flag_job_with_no_score(self):
        flagged, reason = compute_would_apply(None, None)
        assert flagged is False
        assert reason == ""

    def test_dealbreaker_risk_suppresses_flag_even_with_high_score(self):
        flagged, reason = compute_would_apply(9.5, "dealbreaker_risk")
        assert flagged is False
        assert reason == ""

    def test_other_debate_flags_do_not_suppress(self):
        flagged, _ = compute_would_apply(8.0, "underrated")
        assert flagged is True
        flagged, _ = compute_would_apply(8.0, "overrated")
        assert flagged is True
