import json
from unittest.mock import MagicMock, patch

import pytest

import api_client


@pytest.fixture(autouse=True)
def _clean_client_state(tmp_path, monkeypatch):
    """The root tests/conftest.py has its own autouse fixture that registers a
    real JobAgentWeb user and saves a real session cookie for every test in the
    whole suite (this project's own "hit a real backend, not mocks"
    convention). These tests exercise api_client's request-construction logic
    itself — the header/branching/error-message decisions — in isolation from
    that, so they start from a deliberately clean slate: no session file, no
    API key, regardless of what already ran. Applied after that fixture (both
    are function-scoped; this one is requested last, in the test module
    itself, so it runs later in setup) — never touches the real
    ~/.jobagent/session.json for this machine's actual installation."""
    monkeypatch.setattr(api_client, "_SESSION_FILE", tmp_path / "isolated_session.json")
    monkeypatch.setattr(api_client, "JOBAGENT_API_KEY", None)


def _mock_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


class TestLoggedIn:
    def test_false_when_nothing_configured(self):
        assert api_client.logged_in() is False

    def test_true_when_session_file_exists(self):
        api_client._save_cookie("some-cookie-value")
        assert api_client.logged_in() is True

    def test_true_when_api_key_configured_even_without_session_file(self, monkeypatch):
        monkeypatch.setattr(api_client, "JOBAGENT_API_KEY", "my-secret-key")
        assert api_client.logged_in() is True


class TestRequestWithApiKey:
    def test_sends_api_key_header(self, monkeypatch):
        monkeypatch.setattr(api_client, "JOBAGENT_API_KEY", "my-secret-key")
        with patch.object(api_client._client, "request", return_value=_mock_response()) as mock_request:
            api_client.request("GET", "/api/jobs/stats")
        assert mock_request.call_args.kwargs["headers"]["X-JobAgent-Api-Key"] == "my-secret-key"

    def test_no_session_file_required(self, monkeypatch):
        # Regression: this is the entire point of the API key — no session
        # file needs to exist at all, unlike the cookie-based flow.
        monkeypatch.setattr(api_client, "JOBAGENT_API_KEY", "my-secret-key")
        with patch.object(api_client._client, "request", return_value=_mock_response()):
            api_client.request("GET", "/api/jobs/stats")  # must not raise NotLoggedInError

    def test_401_raises_api_key_specific_message(self, monkeypatch):
        monkeypatch.setattr(api_client, "JOBAGENT_API_KEY", "my-secret-key")
        with patch.object(api_client._client, "request", return_value=_mock_response(status_code=401)):
            with pytest.raises(api_client.NotLoggedInError, match="JOBAGENT_API_KEY"):
                api_client.request("GET", "/api/jobs/stats")

    def test_preserves_caller_supplied_headers(self, monkeypatch):
        monkeypatch.setattr(api_client, "JOBAGENT_API_KEY", "my-secret-key")
        with patch.object(api_client._client, "request", return_value=_mock_response()) as mock_request:
            api_client.request("GET", "/api/jobs/stats", headers={"X-Custom": "1"})
        sent_headers = mock_request.call_args.kwargs["headers"]
        assert sent_headers["X-Custom"] == "1"
        assert sent_headers["X-JobAgent-Api-Key"] == "my-secret-key"


class TestRequestWithSessionCookie:
    def test_no_cookie_no_key_raises_not_logged_in(self):
        with pytest.raises(api_client.NotLoggedInError):
            api_client.request("GET", "/api/jobs/stats")

    def test_uses_saved_cookie(self):
        api_client._save_cookie("saved-cookie-value")
        with patch.object(api_client._client, "request", return_value=_mock_response()) as mock_request:
            api_client.request("GET", "/api/jobs/stats")
        mock_request.assert_called_once()

    def test_401_raises_generic_session_message(self):
        api_client._save_cookie("saved-cookie-value")
        with patch.object(api_client._client, "request", return_value=_mock_response(status_code=401)):
            with pytest.raises(api_client.NotLoggedInError, match="scripts/login.py"):
                api_client.request("GET", "/api/jobs/stats")
