import logging

from config import QUERY_PRUNING
from db.repositories import job_repository, search_stats_repository, excluded_search_queries_repository

logger = logging.getLogger(__name__)


def _reject_rate_reason(stats: dict) -> str | None:
    """A query is only judged once it has enough terminally-decided jobs, and stays
    protected while its applied/reviewed share stays above max_success_rate — see
    config.QUERY_PRUNING for why (the baseline reject rate is already high, so raw
    reject-rate alone would prune queries that occasionally surface a real fit along
    with a lot of chaff). This used to be a one-time boolean (any applied/reviewed job,
    ever, blocked pruning forever) — that let a single early hit permanently immunize a
    query even after its success rate collapsed to near-zero over hundreds more jobs, so
    generic broad-match queries were never pruned no matter how reject-heavy they got."""
    terminal_total = stats["terminal_total"]
    if terminal_total < QUERY_PRUNING["min_terminal_sample"]:
        return None
    success_total = stats["applied_total"] + stats["reviewed_total"]
    success_rate = success_total / terminal_total
    if success_rate > QUERY_PRUNING["max_success_rate"]:
        return None
    reject_rate = stats["reject_total"] / terminal_total
    if reject_rate < QUERY_PRUNING["reject_rate_threshold"]:
        return None
    return f"reject rate {reject_rate:.0%} over {terminal_total} jobs, {success_rate:.0%} applied/reviewed"


def prune_queries(source: str | None = None) -> list[dict]:
    """Evaluate every search_query seen for `source` against config.QUERY_PRUNING's
    thresholds and auto-exclude the ones that qualify. Idempotent — exclude() upserts,
    so re-running just refreshes the stored reason. Returns the queries excluded (or
    re-confirmed excluded) this run as [{search_query, reason}, ...]."""
    source = source or QUERY_PRUNING["source"]
    excluded_now: list[dict] = []

    for stats in job_repository.get_query_outcome_stats(source):
        reason = _reject_rate_reason(stats)
        if reason:
            excluded_search_queries_repository.exclude(source, stats["search_query"], reason)
            excluded_now.append({"search_query": stats["search_query"], "reason": reason})

    already = {e["search_query"] for e in excluded_now}
    min_searches = QUERY_PRUNING["min_searches_for_zero_yield"]
    for query in search_stats_repository.get_zero_yield_queries(source, min_searches):
        if query in already:
            continue
        reason = f"found zero new jobs across {min_searches}+ searches (pure duplicate redundancy)"
        excluded_search_queries_repository.exclude(source, query, reason)
        excluded_now.append({"search_query": query, "reason": reason})

    return excluded_now
