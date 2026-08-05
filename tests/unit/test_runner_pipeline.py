import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import web.routes.runner as runner_module
from db.repositories import session_repository
from web.routes.runner import _post_collect_stages, _days_since_last_run, _is_run_active, _RunGuard


@pytest.fixture(autouse=True)
def _reset_run_active():
    runner_module._run_active = False
    runner_module._stage_progress = None
    yield
    runner_module._run_active = False
    runner_module._stage_progress = None


class TestPostCollectStages:
    def test_extractor_runs_before_evaluator_and_ranking(self):
        # evaluator/dealbreakers.py's pre-LLM filter reads structured_data, and jobs
        # never re-enter the "unscored" pool once evaluated — so extraction must
        # happen before evaluation, or the dealbreaker filter never has data to act on.
        labels = [label for label, _, _, _ in _post_collect_stages()]
        assert labels.index("EXTRACTOR") < labels.index("EVALUATOR") < labels.index("AI RANKING")

    def test_all_expected_stages_present_in_order(self):
        labels = [label for label, _, _, _ in _post_collect_stages()]
        assert labels == ["DISTILL PREFERENCES", "EXTRACTOR", "EVALUATOR", "PRUNE QUERIES", "AI RANKING"]

    def test_prune_queries_runs_after_evaluator(self):
        # Query pruning reads job status (rejected/auto_rejected/applied), which is
        # only final once the evaluator has run.
        labels = [label for label, _, _, _ in _post_collect_stages()]
        assert labels.index("EVALUATOR") < labels.index("PRUNE QUERIES")

    def test_extractor_stage_points_at_extract_jobs_script(self):
        stages = {label: path for label, path, _, _ in _post_collect_stages()}
        assert stages["EXTRACTOR"].replace("\\", "/").endswith("scripts/extract_jobs.py")


def _last_finished(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None  # matches JobAgentWeb's actual wire format


class TestDaysSinceLastRun:
    # get_last_collected_at()'s own query semantics (most-recent collected_at,
    # ignoring sessions that finished without ever collecting) are covered in
    # JobAgentWeb's test_sessions.py, not re-derived here.
    def test_no_prior_run_falls_back_to_default(self):
        with patch("web.routes.runner.session_repository.get_last_collected_at", return_value=None):
            assert _days_since_last_run() == 7

    def test_ten_hours_ago_rounds_up_to_one_day(self):
        finished = _last_finished(datetime.utcnow() - timedelta(hours=10))
        with patch("web.routes.runner.session_repository.get_last_collected_at", return_value=finished):
            assert _days_since_last_run() == 1

    def test_just_under_one_day_ago_stays_one_day(self):
        finished = _last_finished(datetime.utcnow() - timedelta(hours=23, minutes=50))
        with patch("web.routes.runner.session_repository.get_last_collected_at", return_value=finished):
            assert _days_since_last_run() == 1

    def test_fifty_hours_ago_rounds_up_to_three_days(self):
        finished = _last_finished(datetime.utcnow() - timedelta(hours=50))
        with patch("web.routes.runner.session_repository.get_last_collected_at", return_value=finished):
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


class TestSessionSpansWholeHandler:
    """Regression: session_repository.start()/finish() used to live only inside
    collector/runner.py, scoped to collection alone — so has_active_run() went
    false the moment collection finished, even though distill/extract/evaluate/
    rank were still running, letting a separately launched process race with
    the dashboard's own run undetected (this happened in production once)."""

    def test_rank_ws_session_is_done_after_a_clean_run(self):
        with patch("web.routes.runner._run_script", return_value=0):
            runner_module._rank_run(MagicMock())
        assert session_repository.get_latest()["status"] == "done"

    def test_rank_ws_session_is_error_if_a_stage_raises(self):
        with patch("web.routes.runner._run_script", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                runner_module._rank_run(MagicMock())
        assert session_repository.get_latest()["status"] == "error"

    def test_agent_ws_session_stays_active_across_every_post_collect_stage(self):
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})
        seen_active = []

        def _fake_run_script(*args, **kwargs):
            seen_active.append(session_repository.has_active_run())
            return 0

        with patch("web.routes.runner._run_script", side_effect=_fake_run_script):
            runner_module._agent_run(mock_ws)

        assert len(seen_active) == 6  # collector + 5 post-collect stages
        assert all(seen_active), "session must stay active through every stage, not just the first"
        assert session_repository.has_active_run() is False  # released once the handler returns
        assert session_repository.get_latest()["status"] == "done"

    def test_agent_ws_passes_the_real_session_id_to_the_collector_stage(self):
        # Regression guard: the outer handler already holds an active session for
        # the whole run before the collector subprocess is spawned. If the
        # collector subprocess called session_repository.start() itself (as it
        # used to), JobAgentWeb's concurrent-session guard rejects it — the
        # collector stage would fail every single "Run Agent" click. Confirms
        # the placeholder in the collector's args is replaced with the real id,
        # not left as the literal placeholder string.
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})
        collector_args = []

        def _fake_run_script(ws, script_path, args=None, log_file=None):
            if "collector" in script_path:
                collector_args.append(args)
            return 0

        with patch("web.routes.runner._run_script", side_effect=_fake_run_script):
            runner_module._agent_run(mock_ws)

        assert len(collector_args) == 1
        assert "--session-id" in collector_args[0]
        session_id_arg = collector_args[0][collector_args[0].index("--session-id") + 1]
        assert session_id_arg == str(session_repository.get_latest()["id"])

    def test_agent_ws_skips_post_collect_stages_when_collector_fails(self):
        # Regression guard for _run_pipeline_ws's stop_if_fails: nothing new was
        # collected, so distill/extract/evaluate/prune/rank have nothing to do —
        # running them anyway would just waste an API-cost cycle on stale data.
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})
        calls = []

        def _fake_run_script(ws, script_path, args=None, log_file=None):
            calls.append(script_path)
            return 1  # collector "fails"

        with patch("web.routes.runner._run_script", side_effect=_fake_run_script):
            runner_module._agent_run(mock_ws)

        assert len(calls) == 1  # only the collector ran, every post-collect stage skipped
        assert session_repository.get_latest()["status"] == "done"  # a handled failure, not an exception

    def test_agent_ws_marks_collected_when_collector_succeeds(self):
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})

        with patch("web.routes.runner._run_script", return_value=0):
            runner_module._agent_run(mock_ws)

        assert session_repository.get_last_collected_at() is not None

    def test_agent_ws_does_not_mark_collected_when_collector_fails(self):
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})

        with patch("web.routes.runner._run_script", return_value=1):
            runner_module._agent_run(mock_ws)

        assert session_repository.get_last_collected_at() is None

    def test_rank_ws_never_marks_collected(self):
        # Regression guard for H3: none of the other 4 handlers ever run a
        # COLLECTOR stage, so none of them should ever advance last-collected.
        with patch("web.routes.runner._run_script", return_value=0):
            runner_module._rank_run(MagicMock())

        assert session_repository.get_last_collected_at() is None


class TestAgentStatus:
    """Covers /api/agent/status's started_at and stage fields, added so a tab
    that closes and reopens the Run Agent modal (or a fresh page load) can
    reattach to an already-in-progress run instead of only ever seeing the
    fresh-start form (see openRunModal/_attachToActiveRun in dashboard.js)."""

    def test_not_running_reports_no_started_at_or_stage(self):
        status = runner_module.agent_status()
        assert status == {"running": False, "started_at": None, "stage": None}

    def test_reports_started_at_and_stage_mid_run(self):
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})
        seen = []

        def _fake_run_script(*args, **kwargs):
            seen.append(runner_module.agent_status())
            return 0

        with patch("web.routes.runner._run_script", side_effect=_fake_run_script):
            runner_module._agent_run(mock_ws)

        assert len(seen) == 6  # collector + 5 post-collect stages
        assert all(s["running"] is True for s in seen)
        assert all(s["started_at"] is not None for s in seen)
        # Same started_at across every stage — the whole run is one session, not
        # a fresh one restarting the clock per stage.
        assert len({s["started_at"] for s in seen}) == 1

        expected_labels = ["COLLECTOR (days=1)"] + [label for label, _, _, _ in _post_collect_stages()]
        assert [s["stage"]["label"] for s in seen] == expected_labels
        assert [s["stage"]["index"] for s in seen] == [1, 2, 3, 4, 5, 6]
        assert all(s["stage"]["total"] == 6 for s in seen)

    def test_stage_and_started_at_cleared_once_run_finishes(self):
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})

        with patch("web.routes.runner._run_script", return_value=0):
            runner_module._agent_run(mock_ws)

        assert runner_module.agent_status() == {"running": False, "started_at": None, "stage": None}

    def test_stage_cleared_even_if_a_stage_raises(self):
        mock_ws = MagicMock()
        mock_ws.receive.return_value = json.dumps({"days": 1})

        with patch("web.routes.runner._run_script", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                runner_module._agent_run(mock_ws)

        assert runner_module._stage_progress is None
