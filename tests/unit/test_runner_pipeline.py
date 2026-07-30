from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import web.routes.runner as runner_module
from web.routes.runner import _post_collect_stages, _days_since_last_run, _is_run_active, _RunGuard


@pytest.fixture(autouse=True)
def _reset_run_active():
    runner_module._run_active = False
    yield
    runner_module._run_active = False


class TestPostCollectStages:
    def test_extractor_runs_before_evaluator_and_ranking(self):
        # evaluator/dealbreakers.py's pre-LLM filter reads structured_data, and jobs
        # never re-enter the "unscored" pool once evaluated — so extraction must
        # happen before evaluation, or the dealbreaker filter never has data to act on.
        labels = [label for label, _, _ in _post_collect_stages()]
        assert labels.index("EXTRACTOR") < labels.index("EVALUATOR") < labels.index("AI RANKING")

    def test_all_expected_stages_present_in_order(self):
        labels = [label for label, _, _ in _post_collect_stages()]
        assert labels == ["DISTILL PREFERENCES", "EXTRACTOR", "EVALUATOR", "PRUNE QUERIES", "AI RANKING"]

    def test_prune_queries_runs_after_evaluator(self):
        # Query pruning reads job status (rejected/auto_rejected/applied), which is
        # only final once the evaluator has run.
        labels = [label for label, _, _ in _post_collect_stages()]
        assert labels.index("EVALUATOR") < labels.index("PRUNE QUERIES")

    def test_extractor_stage_points_at_extract_jobs_script(self):
        stages = {label: path for label, path, _ in _post_collect_stages()}
        assert stages["EXTRACTOR"].replace("\\", "/").endswith("scripts/extract_jobs.py")


def _last_finished(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None  # matches JobAgentWeb's actual wire format


class TestDaysSinceLastRun:
    # get_last_finished_at()'s own query semantics (most-recent "done", ignoring
    # "cancelled") are covered in JobAgentWeb's test_sessions.py, not re-derived here.
    def test_no_prior_run_falls_back_to_default(self):
        with patch("web.routes.runner.session_repository.get_last_finished_at", return_value=None):
            assert _days_since_last_run() == 7

    def test_ten_hours_ago_rounds_up_to_one_day(self):
        finished = _last_finished(datetime.utcnow() - timedelta(hours=10))
        with patch("web.routes.runner.session_repository.get_last_finished_at", return_value=finished):
            assert _days_since_last_run() == 1

    def test_just_under_one_day_ago_stays_one_day(self):
        finished = _last_finished(datetime.utcnow() - timedelta(hours=23, minutes=50))
        with patch("web.routes.runner.session_repository.get_last_finished_at", return_value=finished):
            assert _days_since_last_run() == 1

    def test_fifty_hours_ago_rounds_up_to_three_days(self):
        finished = _last_finished(datetime.utcnow() - timedelta(hours=50))
        with patch("web.routes.runner.session_repository.get_last_finished_at", return_value=finished):
            assert _days_since_last_run() == 3


class TestRunGuard:
    def test_not_active_before_acquiring(self):
        assert _is_run_active() is False

    def test_acquire_succeeds_when_free(self):
        with _RunGuard() as acquired:
            assert acquired is True

    def test_marks_active_while_held(self):
        with _RunGuard():
            assert _is_run_active() is True

    def test_second_acquire_fails_while_first_is_held(self):
        # Regression guard: the old code only held the lock around the initial check,
        # then released it before the slow parts (ws.receive(), subprocess spawn) —
        # so a second near-simultaneous connection could pass the check too.
        with _RunGuard():
            with _RunGuard() as second:
                assert second is False

    def test_releases_after_normal_exit(self):
        with _RunGuard():
            pass
        assert _is_run_active() is False

    def test_releases_even_if_body_raises(self):
        with pytest.raises(ValueError):
            with _RunGuard():
                raise ValueError("boom")
        assert _is_run_active() is False

    def test_can_acquire_again_after_release(self):
        with _RunGuard():
            pass
        with _RunGuard() as acquired:
            assert acquired is True
