from unittest.mock import patch

from web.app import _clear_stale_session_at_startup


class TestClearStaleSessionAtStartup:
    @patch("web.app.session_repository")
    @patch("web.app.api_client")
    def test_does_nothing_when_not_logged_in(self, mock_api_client, mock_session):
        mock_api_client.logged_in.return_value = False
        _clear_stale_session_at_startup()
        mock_session.cancel_active.assert_not_called()

    @patch("web.app.session_repository")
    @patch("web.app.api_client")
    def test_cancels_active_session_when_logged_in(self, mock_api_client, mock_session):
        mock_api_client.logged_in.return_value = True
        _clear_stale_session_at_startup()
        mock_session.cancel_active.assert_called_once()

    @patch("web.app.session_repository")
    @patch("web.app.api_client")
    def test_a_stale_or_invalid_session_does_not_raise(self, mock_api_client, mock_session):
        # Regression: this used to run unwrapped in the `if __name__ == "__main__"`
        # block — a stale/expired cookie (401) or a momentary JobAgentWeb/tunnel
        # hiccup crashed the whole app before it could even serve /login.
        mock_api_client.logged_in.return_value = True
        mock_api_client.NotLoggedInError = Exception
        mock_session.cancel_active.side_effect = Exception("Session expired or invalid")

        _clear_stale_session_at_startup()  # must not raise
