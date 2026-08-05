from unittest.mock import patch

import anthropic
import httpx
import pytest

from ranker.retry import call_with_retry


def _request():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _rate_limit_error():
    return anthropic.RateLimitError("rate limited", response=httpx.Response(429, request=_request()), body=None)


def _internal_server_error():
    # This is also how Anthropic's 529 "overloaded_error" surfaces — any 5xx
    # status maps to InternalServerError in the SDK.
    return anthropic.InternalServerError("overloaded_error", response=httpx.Response(529, request=_request()), body=None)


def _connection_error():
    return anthropic.APIConnectionError(request=_request())


def _bad_request_error():
    return anthropic.BadRequestError("malformed request", response=httpx.Response(400, request=_request()), body=None)


class TestCallWithRetry:
    def test_succeeds_on_first_attempt_no_retry(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        with patch("ranker.retry.time.sleep") as sleep:
            result = call_with_retry(fn, label="test")

        assert result == "ok"
        assert len(calls) == 1
        sleep.assert_not_called()

    def test_retries_a_transient_error_then_succeeds(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise _rate_limit_error()
            return "ok"

        with patch("ranker.retry.time.sleep") as sleep:
            result = call_with_retry(fn, label="test")

        assert result == "ok"
        assert len(calls) == 2
        sleep.assert_called_once()

    def test_retries_internal_server_error_the_overloaded_case(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise _internal_server_error()
            return "ok"

        with patch("ranker.retry.time.sleep"):
            result = call_with_retry(fn, label="test")

        assert result == "ok"
        assert len(calls) == 2

    def test_retries_a_connection_error(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise _connection_error()
            return "ok"

        with patch("ranker.retry.time.sleep"):
            result = call_with_retry(fn, label="test")

        assert result == "ok"
        assert len(calls) == 2

    def test_raises_after_exhausting_every_attempt(self):
        calls = []

        def fn():
            calls.append(1)
            raise _rate_limit_error()

        with patch("ranker.retry.time.sleep") as sleep:
            with pytest.raises(anthropic.RateLimitError):
                call_with_retry(fn, label="test", max_attempts=3)

        assert len(calls) == 3
        assert sleep.call_count == 2  # waits between attempts, not after the last one

    def test_does_not_retry_a_non_transient_error(self):
        # A bad request fails identically on every attempt — retrying it would
        # just waste the wait for a guaranteed-same result.
        calls = []

        def fn():
            calls.append(1)
            raise _bad_request_error()

        with patch("ranker.retry.time.sleep") as sleep:
            with pytest.raises(anthropic.BadRequestError):
                call_with_retry(fn, label="test")

        assert len(calls) == 1
        sleep.assert_not_called()

    def test_backoff_increases_linearly(self):
        calls = []

        def fn():
            calls.append(1)
            raise _rate_limit_error()

        with patch("ranker.retry.time.sleep") as sleep:
            with pytest.raises(anthropic.RateLimitError):
                call_with_retry(fn, label="test", max_attempts=3, base_delay=10)

        assert [c.args[0] for c in sleep.call_args_list] == [10, 20]
