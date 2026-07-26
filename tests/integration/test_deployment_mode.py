import importlib
import pytest
import config


@pytest.fixture
def app_with_mode(monkeypatch):
    """web/app.py registers blueprints at module-import time based on
    config.DEPLOYMENT_MODE, so exercising a different mode means reloading it after
    patching the config value. importlib.reload() mutates the actual cached module
    in sys.modules in place — monkeypatch reverting config.DEPLOYMENT_MODE afterward
    does NOT undo that, so every other test importing web.app would otherwise see
    whatever mode this fixture last reloaded it to. Always reload back to "local"
    (the real default) on teardown to prevent that leaking across tests."""
    def _build(mode):
        monkeypatch.setattr(config, "DEPLOYMENT_MODE", mode)
        import web.app as web_app
        importlib.reload(web_app)
        return web_app.app

    yield _build

    monkeypatch.setattr(config, "DEPLOYMENT_MODE", "local")
    import web.app as web_app
    importlib.reload(web_app)


class TestLocalMode:
    def test_registers_admin_and_pipeline_routes(self, app_with_mode, test_db):
        app = app_with_mode("local")
        client = app.test_client()
        # jobs_admin.bp route
        resp = client.delete("/api/jobs")
        assert resp.status_code != 404
        # criteria.bp route (any pipeline/config blueprint proves "everything" is on)
        resp = client.get("/api/criteria")
        assert resp.status_code != 404


class TestWebMode:
    def test_registers_only_safe_jobs_and_evaluation_routes(self, app_with_mode, test_db):
        app = app_with_mode("web")
        client = app.test_client()
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/stats").status_code == 200
        assert client.get("/api/eval/report").status_code == 200

    def test_admin_routes_are_unreachable(self, app_with_mode, test_db):
        app = app_with_mode("web")
        client = app.test_client()
        # DELETE /api/jobs shares its path with the registered GET /api/jobs, so an
        # unregistered method on an existing path is 405, not 404 — either way the
        # delete can't actually happen, which is what matters here.
        assert client.delete("/api/jobs?status=new").status_code == 405
        assert client.get("/api/jobs/count").status_code == 404
        assert client.get("/api/jobs/missing-descriptions").status_code == 404

    def test_pipeline_and_config_routes_are_unreachable(self, app_with_mode, test_db):
        app = app_with_mode("web")
        client = app.test_client()
        assert client.get("/api/criteria").status_code == 404
        assert client.get("/api/sources").status_code == 404
        assert client.get("/api/search-queries/excluded").status_code == 404

    def test_no_websocket_run_routes(self, app_with_mode, test_db):
        app = app_with_mode("web")
        # runner.init_sock(app) is skipped entirely in web mode — no /ws/* rule at all.
        ws_rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/ws/")]
        assert ws_rules == []
