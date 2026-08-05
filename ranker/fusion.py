import logging

logger = logging.getLogger(__name__)

# Standard IR default (Cormack et al., "Reciprocal Rank Fusion outperforms
# Condorcet and individual rank learning methods") — large enough that a
# single ranking's #1 vs #2 doesn't dominate the fused order, so a job that's
# merely good in both rankings can beat one that's #1 in one and mediocre in
# the other.
_RRF_K = 60


def fuse_by_rrf(jobs: list[dict], k: int = _RRF_K, extra_rank_field: str | None = None) -> list[dict]:
    """Reciprocal Rank Fusion of orderings over the same job list: embedding
    similarity (_embedding_score, higher better), the LLM scorer's score (0-10,
    higher better, None = not yet scored), and optionally a third leg named by
    extra_rank_field. Returns jobs sorted by combined RRF score, descending —
    stable relative to input order for exact ties.

    RRF_score(job) = 1/(k + rank_embedding) + 1/(k + rank_llm_score) [+ 1/(k + rank_extra)]

    Before this, scripts/rank_jobs.py chose the pool feeding rerank/listwise/
    debate purely by embedding rank — the scorer's LLM score was only ever used
    as a >min_score exclusion filter, never to influence ordering. A job scored
    9/10 by the LLM but with only average cosine similarity could sit outside
    the top-N and never reach the paid rerank/listwise stages at all.

    A job missing score (or extra_rank_field, when given) gets no contribution
    from that leg rather than a fabricated rank — it's still eligible purely on
    the remaining leg(s), exactly as before this fusion existed. This is also
    how scripts/rank_jobs.py re-fuses the Voyage cross-encoder back in as a
    third leg (extra_rank_field='rerank_score') after reranking the top-N pool,
    instead of letting the cross-encoder's own order unilaterally decide who
    reaches listwise ranking. This function itself doesn't know whether a
    rerank_score is trustworthy — ranker.reranker.rerank_jobs sets
    _rerank_unreliable on every job when the Voyage call fell back (no query,
    or the API failed), and it's the caller's job to check that marker and skip
    passing extra_rank_field entirely in that case, rather than re-fusing a
    rerank_score that's actually just a copy of the embedding score."""
    if not jobs:
        return []

    # Tie-broken by id, not left to sorted()'s stability: sorted() is stable, and
    # `jobs` arrives from scripts/rank_jobs.py already ordered by embedding score
    # descending — so without an explicit, embedding-independent tiebreaker, any
    # group of jobs sharing the same score (routine; LLM scores are coarse, e.g.
    # whole/half points) would silently keep their *embedding* order within the
    # tie. That's not "no signal from this leg", it's this leg quietly copying
    # the other one, giving embedding similarity extra unearned weight exactly
    # when ties are common. id is unrelated to either leg, so ties resolve the
    # same way regardless of what order `jobs` arrived in.
    def _partial_rank(key: str) -> dict:
        ranked = sorted((j for j in jobs if j.get(key) is not None), key=lambda j: (j[key], j["id"]), reverse=True)
        return {job["id"]: i for i, job in enumerate(ranked)}

    by_embedding = sorted(
        jobs,
        key=lambda j: (j.get("_embedding_score") if j.get("_embedding_score") is not None else float("-inf"), j["id"]),
        reverse=True,
    )
    embedding_rank = {job["id"]: i for i, job in enumerate(by_embedding)}
    llm_rank = _partial_rank("score")
    extra_rank = _partial_rank(extra_rank_field) if extra_rank_field else {}

    def rrf_score(job: dict) -> float:
        total = 1.0 / (k + embedding_rank[job["id"]])
        if job["id"] in llm_rank:
            total += 1.0 / (k + llm_rank[job["id"]])
        if job["id"] in extra_rank:
            total += 1.0 / (k + extra_rank[job["id"]])
        return total

    return sorted(jobs, key=rrf_score, reverse=True)
