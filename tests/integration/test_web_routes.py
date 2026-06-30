import json
import pytest
from db.repositories import job_repository, criteria_repository


def _add_job(flask_client=None, **kwargs):
    """Insert a job directly via the repository (bypasses HTTP)."""
    defaults = dict(title="PHP Developer", company="Acme Corp",
                    location="Poland", url="https://example.com/job/1",
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
        id1 = _add_job(url="https://a.com/1")
        _add_job(company="Beta", url="https://a.com/2")
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
        assert "error" in resp.json

    def test_update_status_all_valid_values_accepted(self, flask_client):
        for status in ("new", "reviewed", "applied", "rejected"):
            job_id = _add_job(
                title="Dev", company=f"Co-{status}",
                url=f"https://a.com/{status}"
            )
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
        for key in ("total", "new", "reviewed", "applied", "rejected", "auto_rejected"):
            assert key in data

    def test_stats_reflects_inserted_jobs(self, flask_client):
        _add_job()
        resp = flask_client.get("/api/stats")
        assert resp.json["total"] == 1
        assert resp.json["new"] == 1


class TestCriteriaEndpoints:
    def test_list_criteria_empty_db(self, flask_client):
        resp = flask_client.get("/api/criteria")
        assert resp.status_code == 200
        assert resp.json == []

    def test_add_then_list_criterion(self, flask_client):
        resp = flask_client.post(
            "/api/criteria",
            data=json.dumps({"type": "title", "value": "PHP Developer"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json["ok"] is True

        items = flask_client.get("/api/criteria").json
        assert len(items) == 1
        assert items[0]["value"] == "PHP Developer"
        assert items[0]["is_active"] == 1

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
        item_id = flask_client.get("/api/criteria").json[0]["id"]
        resp = flask_client.delete(f"/api/criteria/{item_id}")
        assert resp.status_code == 200
        assert flask_client.get("/api/criteria").json == []


class TestAgentStatus:
    def test_returns_not_running_by_default(self, flask_client):
        resp = flask_client.get("/api/agent/status")
        assert resp.status_code == 200
        assert resp.json["running"] is False
