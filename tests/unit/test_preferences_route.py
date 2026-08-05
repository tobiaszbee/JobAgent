from unittest.mock import patch


@patch("web.routes.preferences.usage_repository.record_run_summary")
@patch("web.routes.preferences.preference_runner.run")
def test_distill_records_a_run_summary_on_success(mock_run, mock_record, flask_client):
    # Regression: a manual distill ran an Opus call outside any tracked run,
    # its cost was silently missing from cost_summaries entirely.
    mock_run.return_value = {"ok": True, "signals": []}
    resp = flask_client.post("/api/preferences/distill")
    assert resp.status_code == 200
    mock_record.assert_called_once()
    assert mock_record.call_args[0][0] == "distill_preferences"


@patch("web.routes.preferences.usage_repository.record_run_summary")
@patch("web.routes.preferences.preference_runner.run")
def test_distill_records_a_run_summary_even_on_failure(mock_run, mock_record, flask_client):
    # A failed distill can still have billed a real Anthropic call before
    # erroring, the cost snapshot must not be skipped just because ok=False.
    mock_run.return_value = {"ok": False, "error": "no applied/rejected jobs yet"}
    resp = flask_client.post("/api/preferences/distill")
    assert resp.status_code == 400
    mock_record.assert_called_once()


@patch("web.routes.preferences.usage_repository.record_run_summary")
@patch("web.routes.preferences.preference_runner.run")
def test_distill_records_a_run_summary_even_on_exception(mock_run, mock_record, flask_client):
    mock_run.side_effect = Exception("API error")
    try:
        flask_client.post("/api/preferences/distill")
    except Exception:
        pass
    mock_record.assert_called_once()
