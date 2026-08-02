from unittest.mock import patch

from ranker.would_apply import compute_revocations, compute_would_apply

_MOCK_CONFIG = {"score_floor": 7.0, "rank_ceiling": 10}


@patch("ranker.would_apply.WOULD_APPLY", _MOCK_CONFIG)
class TestComputeWouldApply:
    def test_flags_job_at_or_above_floor_within_rank_ceiling(self):
        flagged, reason = compute_would_apply(7.0, None, listwise_rank=1)
        assert flagged is True
        assert "7.0" in reason

    def test_flags_job_above_floor(self):
        flagged, reason = compute_would_apply(9.0, None, listwise_rank=1)
        assert flagged is True

    def test_does_not_flag_job_below_floor(self):
        flagged, reason = compute_would_apply(6.9, None, listwise_rank=1)
        assert flagged is False
        assert reason == ""

    def test_does_not_flag_job_with_no_score(self):
        flagged, reason = compute_would_apply(None, None, listwise_rank=1)
        assert flagged is False
        assert reason == ""

    def test_dealbreaker_risk_suppresses_flag_even_with_high_score(self):
        flagged, reason = compute_would_apply(9.5, "dealbreaker_risk", listwise_rank=1)
        assert flagged is False
        assert reason == ""

    def test_other_debate_flags_do_not_suppress(self):
        flagged, _ = compute_would_apply(8.0, "underrated", listwise_rank=1)
        assert flagged is True
        flagged, _ = compute_would_apply(8.0, "overrated", listwise_rank=1)
        assert flagged is True

    # --- rank_ceiling (task #49) ---

    def test_flags_job_exactly_at_rank_ceiling(self):
        flagged, reason = compute_would_apply(8.0, None, listwise_rank=10)
        assert flagged is True
        assert "#10" in reason

    def test_does_not_flag_job_beyond_rank_ceiling(self):
        # Regression: score alone used to be the entire gate — a high-scoring job
        # ranked deep in the listwise pool (weaker on Opus/debate's holistic
        # judgment) used to get flagged just as readily as the #1 job.
        flagged, reason = compute_would_apply(9.5, None, listwise_rank=11)
        assert flagged is False
        assert reason == ""

    def test_does_not_flag_job_with_no_rank(self):
        # "only flag with full evidence" — missing rank must not default to
        # flagging, same stance as missing score.
        flagged, reason = compute_would_apply(9.5, None, listwise_rank=None)
        assert flagged is False
        assert reason == ""

    def test_overrated_nudge_can_push_a_job_past_rank_ceiling(self):
        # Deliberate: ranker/debate.py's overrated nudge already moved
        # listwise_rank by the time this runs — no second, separate penalty for
        # the flag itself here, but its effect on rank still applies.
        flagged, _ = compute_would_apply(8.0, "overrated", listwise_rank=11)
        assert flagged is False


class TestComputeRevocations:
    def test_empty_pool_returns_empty(self):
        assert compute_revocations([], set()) == []

    def test_no_previously_flagged_jobs_returns_empty(self):
        pool = [{"id": "j1", "would_apply": False}, {"id": "j2", "would_apply": None}]
        assert compute_revocations(pool, {"j1", "j2"}) == []

    def test_still_flagged_job_not_revoked(self):
        pool = [{"id": "j1", "would_apply": True}]
        assert compute_revocations(pool, {"j1"}) == []

    def test_previously_flagged_job_dropped_from_run_is_revoked(self):
        pool = [{"id": "j1", "would_apply": True}]
        result = compute_revocations(pool, set())
        assert result == [{"job_id": "j1", "would_apply": False, "reason": "No longer in this run's would-apply set"}]

    def test_mixed_pool_only_revokes_the_dropped_ones(self):
        pool = [
            {"id": "j1", "would_apply": True},   # still flagged this run
            {"id": "j2", "would_apply": True},   # dropped out — should be revoked
            {"id": "j3", "would_apply": False},  # was never flagged — nothing to revoke
        ]
        result = compute_revocations(pool, {"j1"})
        assert [r["job_id"] for r in result] == ["j2"]

    def test_job_not_in_pool_is_never_touched(self):
        # Scoped to pool_jobs only — a job outside the pool (changed status, or
        # aged out past the ranking pool's size limit) wasn't re-evaluated this
        # run, so nothing about it is actually known to have changed.
        pool = [{"id": "j1", "would_apply": True}]
        result = compute_revocations(pool, set())
        assert all(r["job_id"] != "j99" for r in result)
