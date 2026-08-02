import json
import stat
import sys
import uuid
from unittest.mock import patch

import pytest
import api_client
from db.repositories import candidate_preferences_repository, cv_repository, job_repository, criteria_repository


def _add_job(**kwargs):
    """Insert a job directly via the repository (bypasses HTTP). job_postings is
    shared/global and never truncated between tests — every call gets its own
    unique url so this test's job never collides with another test's."""
    defaults = dict(title="PHP Developer", company="Acme Corp",
                    location="Poland", url=f"https://example.com/job/{uuid.uuid4().hex}",
                    source="linkedin")
    return job_repository.insert(**{**defaults, **kwargs})


class TestJobsEndpoints:
    def test_list_jobs_empty_db(self, flask_client):
        resp = flask_client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.json == []

    def test_list_jobs_returns_inserted_job(self, flask_client):
        _add_job()
        resp = flask_client.get("/api/jobs")
        assert resp.status_code == 200
        assert len(resp.json) == 1
        assert resp.json[0]["title"] == "PHP Developer"

    def test_list_jobs_status_filter(self, flask_client):
        id1 = _add_job()
        _add_job(company="Beta")
        job_repository.update_status(id1, "reviewed")
        resp = flask_client.get("/api/jobs?status=reviewed")
        assert resp.status_code == 200
        assert len(resp.json) == 1
        assert resp.json[0]["status"] == "reviewed"

    def test_update_status_valid(self, flask_client):
        job_id = _add_job()
        resp = flask_client.post(
            f"/api/jobs/{job_id}/status",
            data=json.dumps({"status": "applied"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json == {"ok": True, "status": "applied"}

    def test_update_status_applied_persisted(self, flask_client):
        job_id = _add_job()
        flask_client.post(
            f"/api/jobs/{job_id}/status",
            data=json.dumps({"status": "applied"}),
            content_type="application/json",
        )
        jobs = flask_client.get("/api/jobs?status=applied").json
        assert len(jobs) == 1

    def test_update_status_invalid_returns_400(self, flask_client):
        job_id = _add_job()
        resp = flask_client.post(
            f"/api/jobs/{job_id}/status",
            data=json.dumps({"status": "auto_rejected"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_list_jobs_passes_the_safety_cap_as_limit(self, flask_client):
        with patch("web.routes.jobs.job_repository.search", return_value=[]) as mock_search:
            flask_client.get("/api/jobs")
        assert mock_search.call_args.kwargs["limit"] == 2000

    def test_list_jobs_not_truncated_header_below_cap(self, flask_client):
        _add_job()
        resp = flask_client.get("/api/jobs")
        assert resp.headers["X-Jobs-Truncated"] == "false"

    def test_list_jobs_truncated_header_when_result_hits_the_cap(self, flask_client):
        # A real 2000-row insert would make this test glacially slow — mock the
        # repository call instead to exercise just the truncation-detection logic.
        fake_results = [{"id": str(i)} for i in range(2000)]
        with patch("web.routes.jobs.job_repository.search", return_value=fake_results):
            resp = flask_client.get("/api/jobs")
        assert resp.headers["X-Jobs-Truncated"] == "true"

    def test_update_status_all_valid_values_accepted(self, flask_client):
        for status in ("new", "reviewed", "applied", "rejected"):
            job_id = _add_job(title="Dev", company=f"Co-{status}")
            resp = flask_client.post(
                f"/api/jobs/{job_id}/status",
                data=json.dumps({"status": status}),
                content_type="application/json",
            )
            assert resp.status_code == 200

    def test_stats_endpoint_structure(self, flask_client):
        resp = flask_client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json
        for key in ("total", "new", "reviewed", "applied", "rejected", "auto_rejected", "last_run"):
            assert key in data

    def test_stats_reflects_inserted_jobs(self, flask_client):
        _add_job()
        resp = flask_client.get("/api/stats")
        assert resp.json["total"] == 1
        assert resp.json["new"] == 1


class TestDismissItemEndpoints:
    def test_dismiss_con_returns_ok(self, flask_client):
        job_id = _add_job()
        resp = flask_client.post(
            f"/api/jobs/{job_id}/dismiss-item",
            data=json.dumps({"item_type": "con", "item_text": "UK-based, timezone concern", "reason": "not an issue for me"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json == {"ok": True}

    def test_dismissed_item_then_listed(self, flask_client):
        job_id = _add_job()
        flask_client.post(
            f"/api/jobs/{job_id}/dismiss-item",
            data=json.dumps({"item_type": "pro", "item_text": "Fully remote", "reason": "I actually prefer hybrid"}),
            content_type="application/json",
        )
        resp = flask_client.get(f"/api/jobs/{job_id}/dismissed-items")
        assert resp.status_code == 200
        assert len(resp.json["items"]) == 1
        assert resp.json["items"][0]["item_text"] == "Fully remote"
        assert resp.json["items"][0]["reason"] == "I actually prefer hybrid"

    def test_no_dismissed_items_returns_empty_list(self, flask_client):
        job_id = _add_job()
        resp = flask_client.get(f"/api/jobs/{job_id}/dismissed-items")
        assert resp.json == {"items": []}

    def test_invalid_item_type_returns_400(self, flask_client):
        job_id = _add_job()
        resp = flask_client.post(
            f"/api/jobs/{job_id}/dismiss-item",
            data=json.dumps({"item_type": "neutral", "item_text": "X", "reason": "Y"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_missing_reason_returns_400(self, flask_client):
        job_id = _add_job()
        resp = flask_client.post(
            f"/api/jobs/{job_id}/dismiss-item",
            data=json.dumps({"item_type": "con", "item_text": "X", "reason": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_missing_item_text_returns_400(self, flask_client):
        job_id = _add_job()
        resp = flask_client.post(
            f"/api/jobs/{job_id}/dismiss-item",
            data=json.dumps({"item_type": "con", "item_text": "", "reason": "Y"}),
            content_type="application/json",
        )
        assert resp.status_code == 400


class TestJobsMiscEndpoints:
    def test_missing_descriptions_returns_count(self, flask_client):
        job_repository.insert("Dev", "Co", "PL", f"https://a.com/{uuid.uuid4().hex}", "linkedin")
        resp = flask_client.get("/api/jobs/missing-descriptions")
        assert resp.status_code == 200
        assert resp.json["count"] == 1

    def test_missing_descriptions_zero_when_all_have_desc(self, flask_client):
        job_id = _add_job()
        job_repository.update_description(job_id, "Full job description here.")
        resp = flask_client.get("/api/jobs/missing-descriptions")
        assert resp.status_code == 200
        assert resp.json["count"] == 0

    def test_delete_job_with_dismissed_score_item_does_not_500(self, flask_client):
        # Regression: DELETE /api/jobs?status=... 500'd with "FOREIGN KEY constraint
        # failed" for any job that had a dismissed pro/con, because the referencing
        # table lacked ON DELETE CASCADE. Reproduces the exact reported request shape.
        job_id = _add_job()
        flask_client.post(
            f"/api/jobs/{job_id}/dismiss-item",
            data=json.dumps({"item_type": "con", "item_text": "No salary shown", "reason": "not an issue for me"}),
            content_type="application/json",
        )
        resp = flask_client.delete("/api/jobs?status=auto_rejected&status=new&status=reviewed")
        assert resp.status_code == 200
        assert resp.json["deleted"] == 1


class TestCriteriaEndpoints:
    def test_list_criteria_returns_empty_list_by_default(self, flask_client):
        resp = flask_client.get("/api/criteria")
        assert resp.status_code == 200
        assert resp.json == []

    def test_add_then_list_criterion(self, flask_client):
        before = len(flask_client.get("/api/criteria").json)
        resp = flask_client.post(
            "/api/criteria",
            data=json.dumps({"type": "title", "value": "PHP Developer"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json["ok"] is True

        items = flask_client.get("/api/criteria").json
        assert len(items) == before + 1
        added = next(i for i in items if i["value"] == "PHP Developer")
        assert added["is_active"] == 1

    def test_add_criterion_invalid_type_returns_400(self, flask_client):
        resp = flask_client.post(
            "/api/criteria",
            data=json.dumps({"type": "invalid_type", "value": "something"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_add_criterion_missing_value_returns_400(self, flask_client):
        resp = flask_client.post(
            "/api/criteria",
            data=json.dumps({"type": "title"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_add_criterion_missing_type_returns_400(self, flask_client):
        resp = flask_client.post(
            "/api/criteria",
            data=json.dumps({"value": "something"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_toggle_criterion_deactivates(self, flask_client):
        flask_client.post(
            "/api/criteria",
            data=json.dumps({"type": "title", "value": "PHP Dev"}),
            content_type="application/json",
        )
        item_id = flask_client.get("/api/criteria").json[0]["id"]
        resp = flask_client.post(
            f"/api/criteria/{item_id}/toggle",
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json["ok"] is True
        items = flask_client.get("/api/criteria").json
        assert items[0]["is_active"] == 0

    def test_delete_criterion(self, flask_client):
        flask_client.post(
            "/api/criteria",
            data=json.dumps({"type": "title", "value": "PHP Dev"}),
            content_type="application/json",
        )
        item_id = next(i["id"] for i in flask_client.get("/api/criteria").json if i["value"] == "PHP Dev")
        resp = flask_client.delete(f"/api/criteria/{item_id}")
        assert resp.status_code == 200
        remaining = [i["value"] for i in flask_client.get("/api/criteria").json]
        assert "PHP Dev" not in remaining


class TestAgentStatus:
    def test_returns_not_running_by_default(self, flask_client):
        resp = flask_client.get("/api/agent/status")
        assert resp.status_code == 200
        assert resp.json["running"] is False


class TestExcludedSearchQueriesEndpoints:
    def test_list_empty_by_default(self, flask_client):
        resp = flask_client.get("/api/search-queries/excluded")
        assert resp.status_code == 200
        assert resp.json == []

    def test_list_reflects_excluded_query(self, flask_client):
        from db.repositories import excluded_search_queries_repository
        excluded_search_queries_repository.exclude("linkedin", "PHP Developer", "reject rate 97% over 30 jobs")

        resp = flask_client.get("/api/search-queries/excluded")
        assert resp.status_code == 200
        assert len(resp.json) == 1
        assert resp.json[0]["search_query"] == "PHP Developer"

    def test_reinstate_removes_it(self, flask_client):
        from db.repositories import excluded_search_queries_repository
        excluded_search_queries_repository.exclude("linkedin", "PHP Developer", "reason")
        id_ = excluded_search_queries_repository.get_all()[0]["id"]

        resp = flask_client.post(f"/api/search-queries/excluded/{id_}/reinstate")
        assert resp.status_code == 200
        assert flask_client.get("/api/search-queries/excluded").json == []


class TestRootRouting:
    def test_root_shows_landing_when_no_preferences_saved(self, flask_client):
        resp = flask_client.get("/")
        assert resp.status_code == 200
        assert b"Upload your CV" in resp.data

    def test_root_shows_dashboard_when_preferences_saved(self, flask_client):
        candidate_preferences_repository.insert(None, {"open_notes": "test"})
        resp = flask_client.get("/")
        assert resp.status_code == 200
        assert b"JobAgent" in resp.data and b"Dashboard" in resp.data


class TestQuestionnaireRouting:
    def test_redirects_to_root_without_a_cv(self, flask_client):
        resp = flask_client.get("/questionnaire")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_renders_when_cv_exists(self, flask_client):
        cv_repository.insert("resume.pdf", "raw text", {"stack": ["PHP"]})
        resp = flask_client.get("/questionnaire")
        assert resp.status_code == 200
        assert b"A few questions to match more precisely" in resp.data


class TestLoginRouting:
    def test_login_page_renders_when_logged_out(self, flask_client):
        api_client._SESSION_FILE.unlink()
        resp = flask_client.get("/login")
        assert resp.status_code == 200
        assert b"Log in" in resp.data

    def test_protected_route_redirects_to_login_when_logged_out(self, flask_client):
        api_client._SESSION_FILE.unlink()
        resp = flask_client.get("/")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/login"

    def test_login_post_invalid_credentials_shows_error(self, flask_client):
        api_client._SESSION_FILE.unlink()
        resp = flask_client.post("/login", data={"username": "nope-does-not-exist", "password": "wrong"})
        assert resp.status_code == 200
        assert b"Login failed" in resp.data

    def test_login_post_valid_credentials_redirects_and_restores_session(self, flask_client, _isolated_user):
        username = _isolated_user
        api_client._SESSION_FILE.unlink()
        resp = flask_client.post("/login", data={"username": username, "password": "test-password-not-real"})
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        assert api_client.logged_in()

    def test_session_file_is_owner_only_on_posix(self, flask_client, _isolated_user):
        # session.json is a live, unattended login for this JobAgentWeb account —
        # on a shared machine, default permissions would hand it to anyone else
        # on the box. No-op on Windows (POSIX mode bits don't map to NTFS ACLs).
        if sys.platform == "win32":
            pytest.skip("chmod is a no-op on Windows — nothing to assert here")
        mode = stat.S_IMODE(api_client._SESSION_FILE.stat().st_mode)
        assert mode == 0o600


class TestApiClientReusedConnection:
    def test_switching_active_user_does_not_leak_previous_users_jobs(self, flask_client, _isolated_user):
        # Regression: api_client reuses one httpx.Client across every call instead
        # of opening a fresh connection per request. httpx auto-captures Set-Cookie
        # from every response into that client's own persistent jar by default, and
        # JobAgentWeb's SessionMiddleware re-signs the session cookie on every
        # response — so the auto-captured cookie and api_client's own explicit
        # cookie-set could coexist as two separate entries in the jar instead of
        # one replacing the other, and a later request could end up sending the
        # stale one. Reproduced directly: registering a second user in the same
        # process without clearing the jar first leaked the first user's jobs.
        _add_job()
        assert len(api_client.get("/api/jobs").json()) == 1

        other_username = f"switchtest_{uuid.uuid4().hex[:12]}"
        api_client.register(other_username, "test-password-not-real", invite_code="test-invite-code")
        assert api_client.get("/api/jobs").json() == []
