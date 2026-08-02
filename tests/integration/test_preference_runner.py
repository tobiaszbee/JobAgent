import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from db.repositories import job_repository, preference_repository, dismissed_item_repository
from preference_agent.runner import run


def _unique_url(url: str) -> str:
    """job_postings is shared/global and never truncated between tests — reusing
    a literal url would reuse another test's stale posting fields instead of
    creating a fresh one for this test."""
    return f"{url}?t={uuid.uuid4().hex}"


def _insert_applied(url="https://example.com/applied/1", **kwargs):
    defaults = dict(title="Senior PHP Dev", company="ProductCo",
                    location="Remote", source="linkedin",
                    description="Product SaaS, B2B, async remote.")
    job_id = job_repository.insert(**{**defaults, "url": _unique_url(url), **kwargs})
    job_repository.update_status(job_id, "applied")
    return job_id


def _insert_rejected(url="https://example.com/rejected/1", rejection_reason="agency model", **kwargs):
    defaults = dict(title="PHP Developer", company="AgencyCo",
                    location="Remote", source="linkedin",
                    description="Outsourcing agency.")
    job_id = job_repository.insert(**{**defaults, "url": _unique_url(url), **kwargs})
    job_repository.update_status(job_id, "rejected", rejection_reason=rejection_reason)
    return job_id


_SIGNALS = [
    {"type": "ACCEPT", "dim": "company_type", "value": "product_saas", "conf": "HIGH", "n_match": 1, "n_total": 1},
    {"type": "REJECT", "dim": "company_type", "value": "agency", "conf": "ABSOLUTE", "n_match": 1, "n_total": 1, "note": "agency model"},
    {"type": "NEUTRAL", "dim": "compensation"},
]


def _mock_response(signals=None, stop_reason="tool_use"):
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {"signals": signals if signals is not None else _SIGNALS}
    response = MagicMock()
    response.stop_reason = stop_reason
    response.content = [tool_block]
    return response


@contextmanager
def _patched_api(response=None):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = response or _mock_response()
    with patch("preference_agent.runner.anthropic.Anthropic", return_value=mock_client) as mock_cls:
        yield mock_client, mock_cls


class TestPreferenceRunner:
    def test_no_data_returns_no_data(self):
        result = run()
        assert result == {"ok": False, "reason": "no_data"}

    def test_successful_run_saves_to_db(self):
        _insert_applied()
        _insert_rejected()
        with _patched_api():
            result = run()
        assert result["ok"]
        assert result["signals"] == _SIGNALS
        profile = preference_repository.get_latest()
        assert profile is not None
        assert profile["signals"] == _SIGNALS
        assert profile["applied_count"] == 1
        assert profile["rejected_count"] == 1

    def test_successful_run_returns_rendered_content(self):
        _insert_applied()
        _insert_rejected()
        with _patched_api():
            result = run()
        assert "ACCEPT[company_type=product_saas" in result["content"]
        assert "REJECT[company_type=agency" in result["content"]
        assert "NEUTRAL[compensation; no_signal]" in result["content"]

    def test_no_new_data_skips_api(self):
        _insert_applied()
        _insert_rejected()
        preference_repository.save(_SIGNALS, applied_count=1, rejected_count=1)
        with _patched_api() as (mock_client, _):
            result = run()
        assert result["ok"]
        assert result["reason"] == "no_new_data"
        mock_client.messages.create.assert_not_called()

    def test_no_new_data_returns_existing_signals(self):
        _insert_applied()
        _insert_rejected()
        preference_repository.save(_SIGNALS, applied_count=1, rejected_count=1)
        with _patched_api():
            result = run()
        assert result["signals"] == _SIGNALS

    def test_truncated_response_not_saved(self):
        _insert_applied()
        _insert_rejected()
        with _patched_api(_mock_response(stop_reason="max_tokens")):
            result = run()
        assert result == {"ok": False, "reason": "truncated"}
        assert preference_repository.get_latest() is None

    def test_no_tool_block_not_saved(self):
        _insert_applied()
        _insert_rejected()
        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = []
        with _patched_api(response):
            result = run()
        assert result == {"ok": False, "reason": "no_tool_block"}
        assert preference_repository.get_latest() is None

    def test_empty_signals_not_saved(self):
        _insert_applied()
        _insert_rejected()
        with _patched_api(_mock_response(signals=[])):
            result = run()
        assert result == {"ok": False, "reason": "empty_signals"}
        assert preference_repository.get_latest() is None

    def test_invalid_signal_missing_dim_not_saved(self):
        _insert_applied()
        _insert_rejected()
        bad_signals = [{"type": "ACCEPT"}]  # missing dim
        with _patched_api(_mock_response(signals=bad_signals)):
            result = run()
        assert result["ok"] is False
        assert result["reason"] == "invalid_signal"
        assert preference_repository.get_latest() is None

    def test_invalid_signal_unknown_type_not_saved(self):
        _insert_applied()
        _insert_rejected()
        bad_signals = [{"type": "PREFER", "dim": "company_type"}]
        with _patched_api(_mock_response(signals=bad_signals)):
            result = run()
        assert result["ok"] is False
        assert result["reason"] == "invalid_signal"
        assert preference_repository.get_latest() is None

    def test_one_bad_signal_among_valid_ones_is_dropped_not_fatal(self):
        # Regression: a single malformed signal out of potentially dozens used
        # to discard the entire (expensive) distillation response instead of
        # just filtering out the bad entry.
        _insert_applied()
        _insert_rejected()
        mixed_signals = [
            {"type": "ACCEPT", "dim": "company_type", "value": "product_saas", "conf": "HIGH", "n_match": 1, "n_total": 1},
            {"type": "PREFER", "dim": "broken"},  # invalid type — should be dropped
            {"type": "REJECT", "dim": "compensation"},  # valid — should be kept
        ]
        with _patched_api(_mock_response(signals=mixed_signals)):
            result = run()
        assert result["ok"] is True
        assert len(result["signals"]) == 2
        assert {s["dim"] for s in result["signals"]} == {"company_type", "compensation"}
        assert preference_repository.get_latest() is not None

    def test_api_exception_returns_error(self):
        _insert_applied()
        _insert_rejected()
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("connection timeout")
        with patch("preference_agent.runner.anthropic.Anthropic", return_value=mock_client):
            result = run()
        assert result["ok"] is False
        assert "connection timeout" in result["reason"]

    def test_new_feedback_triggers_redistillation(self):
        _insert_applied()
        _insert_rejected()
        preference_repository.save(_SIGNALS, applied_count=1, rejected_count=0)  # stale count
        new_signals = [{"type": "REJECT", "dim": "company_type", "value": "agency", "conf": "HIGH", "n_match": 1, "n_total": 1}]
        with _patched_api(_mock_response(signals=new_signals)):
            result = run()
        assert result["ok"]
        assert result["signals"] == new_signals

    def test_only_applied_jobs_triggers_run(self):
        _insert_applied()
        with _patched_api():
            result = run()
        assert result["ok"]

    def test_prompt_includes_feedback_data(self):
        _insert_applied(url="https://example.com/a/1")
        _insert_rejected(url="https://example.com/r/1")
        with _patched_api() as (mock_client, _):
            run()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        prompt_content = call_kwargs["messages"][0]["content"]
        assert "APPLIED" in prompt_content
        assert "REJECTED" in prompt_content

    def test_dismissed_only_triggers_run(self):
        # No applied/rejected feedback at all — a lone dismissed score factor must
        # still be enough to run distillation, not just apply/reject decisions.
        jid = job_repository.insert(
            title="Dev", company="Corp", location="Remote", source="linkedin",
            url=_unique_url("https://example.com/dismiss/1"), description="PHP role.",
        )
        dismissed_item_repository.insert(jid, "con", "UK-based, timezone concern", "not an issue for me")
        with _patched_api() as (mock_client, _):
            result = run()
        assert result["ok"]
        mock_client.messages.create.assert_called_once()

    def test_prompt_includes_dismissed_section(self):
        _insert_applied()
        job_id = job_repository.insert(
            title="Dev", company="Corp", location="Remote", source="linkedin",
            url=_unique_url("https://example.com/dismiss/2"), description="PHP role.",
        )
        dismissed_item_repository.insert(job_id, "con", "UK-based, timezone concern", "not an issue for me")
        with _patched_api() as (mock_client, _):
            run()
        prompt_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "DISMISSED SCORE FACTORS" in prompt_content
        assert "UK-based, timezone concern" in prompt_content
        assert "not an issue for me" in prompt_content

    def test_new_dismissed_item_triggers_redistillation_even_if_counts_unchanged(self):
        _insert_applied()
        _insert_rejected()
        preference_repository.save(_SIGNALS, applied_count=1, rejected_count=1, dismissed_count=0)
        job_id = job_repository.insert(
            title="Dev", company="Corp", location="Remote", source="linkedin",
            url=_unique_url("https://example.com/dismiss/3"), description="PHP role.",
        )
        dismissed_item_repository.insert(job_id, "con", "New concern", "reason")
        with _patched_api() as (mock_client, _):
            result = run()
        assert result["ok"]
        mock_client.messages.create.assert_called_once()

    def test_no_new_dismissed_items_still_skips(self):
        _insert_applied()
        _insert_rejected()
        job_id = job_repository.insert(
            title="Dev", company="Corp", location="Remote", source="linkedin",
            url=_unique_url("https://example.com/dismiss/4"), description="PHP role.",
        )
        dismissed_item_repository.insert(job_id, "con", "A concern", "reason")
        preference_repository.save(_SIGNALS, applied_count=1, rejected_count=1, dismissed_count=1)
        with _patched_api() as (mock_client, _):
            result = run()
        assert result["ok"]
        assert result["reason"] == "no_new_data"
        mock_client.messages.create.assert_not_called()
