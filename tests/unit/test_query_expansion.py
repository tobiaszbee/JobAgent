import logging
from unittest.mock import MagicMock, patch

import pytest


def _applied_jobs(n: int) -> list[dict]:
    return [{"title": f"Dev {i}", "company": f"Corp {i}"} for i in range(n)]


def _make_tool_response(queries: list[str], rationale: str = "good reasons"):
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"queries": queries, "rationale": rationale}
    response = MagicMock()
    response.content = [block]
    return response


def _mock_client(create_return=None, create_side_effect=None):
    client = MagicMock()
    if create_side_effect is not None:
        client.messages.create.side_effect = create_side_effect
    else:
        client.messages.create.return_value = create_return
    return client


@patch("db.repositories.criteria_repository.get_active", return_value=[])
@patch("db.repositories.job_repository.get_all_feedback")
@patch("query_expansion.runner._get_client")
def test_suggest_queries_returns_ok_true_on_success(mock_get_client, mock_get_feedback, mock_get_active):
    mock_get_feedback.return_value = (_applied_jobs(5), [])
    mock_get_client.return_value = _mock_client(
        create_return=_make_tool_response(["python developer remote", "django backend engineer"])
    )

    from query_expansion.runner import suggest_queries
    result = suggest_queries()

    assert result["ok"] is True
    assert "python developer remote" in result["queries"]
    assert result["rationale"] == "good reasons"


@patch("query_expansion.runner.log_anthropic")
@patch("db.repositories.criteria_repository.get_active", return_value=[])
@patch("db.repositories.job_repository.get_all_feedback")
@patch("query_expansion.runner._get_client")
def test_suggest_queries_logs_anthropic_usage(mock_get_client, mock_get_feedback, mock_get_active, mock_log):
    # Regression: this call site never reported cost, so the usage dashboard
    # undercounted real Anthropic spend for this user-triggered action.
    mock_get_feedback.return_value = (_applied_jobs(5), [])
    response = _make_tool_response(["python developer remote"])
    mock_get_client.return_value = _mock_client(create_return=response)

    from query_expansion.runner import suggest_queries
    suggest_queries()

    mock_log.assert_called_once()
    assert mock_log.call_args.args[0] is response


@patch("db.repositories.job_repository.get_all_feedback")
def test_suggest_queries_requires_at_least_3_applied(mock_get_feedback):
    mock_get_feedback.return_value = (_applied_jobs(2), [])

    from query_expansion.runner import suggest_queries
    result = suggest_queries()

    assert result["ok"] is False
    assert result["queries"] == []


@patch("db.repositories.criteria_repository.get_active", return_value=[])
@patch("db.repositories.job_repository.get_all_feedback")
@patch("query_expansion.runner._get_client")
def test_suggest_queries_handles_api_error(mock_get_client, mock_get_feedback, mock_get_active):
    mock_get_feedback.return_value = (_applied_jobs(5), [])
    mock_get_client.return_value = _mock_client(create_side_effect=Exception("Anthropic down"))

    from query_expansion.runner import suggest_queries
    result = suggest_queries()

    assert result["ok"] is False
    assert result["queries"] == []


@patch("db.repositories.criteria_repository.get_active", return_value=[])
@patch("db.repositories.job_repository.get_all_feedback")
@patch("query_expansion.runner._get_client")
def test_suggest_queries_handles_no_tool_block(mock_get_client, mock_get_feedback, mock_get_active):
    mock_get_feedback.return_value = (_applied_jobs(5), [])
    response = MagicMock()
    response.content = []
    mock_get_client.return_value = _mock_client(create_return=response)

    from query_expansion.runner import suggest_queries
    result = suggest_queries()

    assert result["ok"] is False
    assert "No response from model" in result["reason"]


@patch("db.repositories.criteria_repository.get_active", return_value=["python developer", "django"])
@patch("db.repositories.job_repository.get_all_feedback")
@patch("query_expansion.runner._get_client")
def test_suggest_queries_includes_existing_queries_in_prompt(mock_get_client, mock_get_feedback, mock_get_active):
    mock_get_feedback.return_value = (_applied_jobs(5), [])
    prompts_sent = []

    def capture_call(**kwargs):
        prompts_sent.append(kwargs["messages"][0]["content"])
        return _make_tool_response(["new query"])

    mock_get_client.return_value = _mock_client()
    mock_get_client.return_value.messages.create.side_effect = capture_call

    from query_expansion.runner import suggest_queries
    suggest_queries()

    assert len(prompts_sent) == 1
    assert "python developer" in prompts_sent[0]


class TestApplyRoute:
    def test_failed_insert_is_logged_and_excluded_from_added_count(self, flask_client, caplog):
        # Regression guard: this used to be a bare `except Exception: pass` — a
        # real failure (JobAgentWeb down, session expired) looked identical to
        # a silently-skipped duplicate, with zero signal anywhere it happened.
        def fake_insert(type_, value):
            if value == "bad query":
                raise RuntimeError("boom")

        with patch("db.repositories.criteria_repository.insert", side_effect=fake_insert):
            with caplog.at_level(logging.WARNING):
                resp = flask_client.post("/api/query-expansion/apply", json={"queries": ["good query", "bad query"]})

        assert resp.status_code == 200
        assert resp.get_json()["added"] == 1
        assert "bad query" in caplog.text
