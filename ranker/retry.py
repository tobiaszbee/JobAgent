import logging
import time

import anthropic

logger = logging.getLogger(__name__)

# Worth retrying: transient — a network blip, a rate limit, or the API's own
# 5xx (this is also how Anthropic's 529 "overloaded" error surfaces, since the
# SDK maps any 5xx status to InternalServerError). Everything else (bad
# request, auth, permission, not found, a malformed request) fails identically
# on a second attempt, so retrying it would just waste the wait.
_RETRYABLE = (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError, anthropic.InternalServerError)


def call_with_retry(fn, *, label: str, max_attempts: int = 3, base_delay: float = 30):
    """Calls fn() (a zero-arg callable wrapping a single Anthropic API call),
    retrying a transient failure with linear backoff (base_delay, 2*base_delay, ...).
    Raises the last exception once every attempt is exhausted, or immediately for
    a non-transient error.

    evaluator/scorer.py has its own inline version of this (predates this module,
    narrower — only retries when "overloaded" appears in the error text). This one
    is for ranker/listwise.py and ranker/debate.py, which previously had no retry
    at all: a single transient hiccup on either fell straight through to their
    fallback (rerank order / unreviewed), silently discarding the most expensive,
    highest-value call in the whole pipeline for that run."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except _RETRYABLE as e:
            if attempt == max_attempts - 1:
                raise
            wait = base_delay * (attempt + 1)
            logger.warning(
                f"{label} failed ({type(e).__name__}: {e}) — retrying in {wait}s "
                f"(attempt {attempt + 1}/{max_attempts})..."
            )
            time.sleep(wait)
