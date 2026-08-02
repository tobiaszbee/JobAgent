import time

import pytest

import api_client
from db.repositories import session_repository
from web.routes.runner import _days_since_last_run


class TestStart:
    def test_returns_integer_id(self):
        session_id = session_repository.start()
        assert isinstance(session_id, int)
        assert session_id > 0

    def test_each_call_returns_unique_id(self):
        id1 = session_repository.start()
        session_repository.finish(id1, jobs_found=0, jobs_scored=0)
        id2 = session_repository.start()
        assert id1 != id2

    def test_second_start_while_one_is_running_raises(self):
        # A run launched directly from a terminal used to have no guard at all
        # against a second concurrent run — only the dashboard's in-process
        # _RunGuard did, which a terminal invocation bypasses entirely. This is
        # now enforced server-side, so it holds regardless of which client starts it.
        session_repository.start()
        with pytest.raises(api_client.ApiError) as exc_info:
            session_repository.start()
        assert exc_info.value.status_code == 409


class TestFinish:
    def test_updates_session_to_done(self):
        sid = session_repository.start()
        session_repository.finish(sid, jobs_found=10, jobs_scored=5)
        latest = session_repository.get_latest()
        assert latest["status"] == "done"
        assert latest["jobs_found"] == 10
        assert latest["jobs_scored"] == 5

    def test_accepts_custom_status(self):
        sid = session_repository.start()
        session_repository.finish(sid, jobs_found=0, jobs_scored=0, status="error")
        latest = session_repository.get_latest()
        assert latest["status"] == "error"

    def test_sets_finished_at_timestamp(self):
        sid = session_repository.start()
        session_repository.finish(sid, jobs_found=1, jobs_scored=1)
        latest = session_repository.get_latest()
        assert latest["finished_at"] is not None


class TestCancelActive:
    def test_cancels_running_sessions(self):
        session_repository.start()
        session_repository.cancel_active()
        assert not session_repository.has_active_run()

    def test_does_nothing_when_no_active_session(self):
        session_repository.cancel_active()  # should not raise
        assert not session_repository.has_active_run()


class TestHasActiveRun:
    def test_false_when_no_sessions(self):
        assert not session_repository.has_active_run()

    def test_true_after_starting_session(self):
        session_repository.start()
        assert session_repository.has_active_run()

    def test_false_after_finishing_session(self):
        sid = session_repository.start()
        session_repository.finish(sid, jobs_found=0, jobs_scored=0)
        assert not session_repository.has_active_run()


class TestGetLatest:
    def test_returns_none_when_no_sessions(self):
        assert session_repository.get_latest() is None

    def test_returns_most_recent_session(self):
        sid1 = session_repository.start()
        session_repository.finish(sid1, 5, 3)
        sid2 = session_repository.start()
        latest = session_repository.get_latest()
        assert latest["id"] == sid2

    def test_returns_dict_with_expected_keys(self):
        session_repository.start()
        latest = session_repository.get_latest()
        assert "id" in latest
        assert "status" in latest
        assert "started_at" in latest


class TestMarkCollected:
    def test_last_collected_is_none_until_marked(self):
        sid = session_repository.start()
        session_repository.finish(sid, jobs_found=0, jobs_scored=0)
        assert session_repository.get_last_collected_at() is None

    def test_mark_collected_sets_last_collected(self):
        sid = session_repository.start()
        session_repository.mark_collected(sid)
        assert session_repository.get_last_collected_at() is not None

    def test_finish_alone_does_not_count_as_collected(self):
        # Regression: a ranking/rescoring/re-evaluating session finishes 'done'
        # exactly like a real collection does — only an explicit mark_collected()
        # call (from the collector stage itself) should move this forward.
        sid = session_repository.start()
        session_repository.finish(sid, jobs_found=5, jobs_scored=5, status="done")
        assert session_repository.get_last_collected_at() is None


class TestDaysSinceLastRunAgainstRealApi:
    # Regression guard: JobAgentWeb serializes collected_at as ISO, not SQLite's old space-separated format.
    def test_freshly_collected_session_reports_one_day(self):
        sid = session_repository.start()
        session_repository.mark_collected(sid)
        session_repository.finish(sid, jobs_found=1, jobs_scored=1)
        assert _days_since_last_run() == 1

    def test_a_finished_but_never_collected_session_does_not_count(self):
        # Regression guard for the H3 bug: clicking "AI Ranking" (or any other
        # non-collector action) must not narrow tomorrow's collection window.
        sid = session_repository.start()
        session_repository.finish(sid, jobs_found=0, jobs_scored=0)
        assert _days_since_last_run() == 7  # falls back to the no-prior-run default
