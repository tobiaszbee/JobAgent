import time
from db.repositories import session_repository


class TestStart:
    def test_returns_integer_id(self):
        session_id = session_repository.start()
        assert isinstance(session_id, int)
        assert session_id > 0

    def test_each_call_returns_unique_id(self):
        id1 = session_repository.start()
        id2 = session_repository.start()
        assert id1 != id2


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
