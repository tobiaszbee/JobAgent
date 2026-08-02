import logging

logger = logging.getLogger(__name__)

# Standard IR default (Cormack et al., "Reciprocal Rank Fusion outperforms
# Condorcet and individual rank learning methods") — large enough that a
# single ranking's #1 vs #2 doesn't dominate the fused order, so a job that's
# merely good in both rankings can beat one that's #1 in one and mediocre in
# the other.
_RRF_K = 60


def fuse_by_rrf(jobs: list[dict], k: int = _RRF_K) -> list[dict]:
    """Reciprocal Rank Fusion of two orderings over the same job list: embedding
    similarity (_embedding_score, higher better) and the LLM scorer's score
    (0-10, higher better, None = not yet scored). Returns jobs sorted by combined
    RRF score, descending — stable relative to input order for exact ties.

    RRF_score(job) = 1/(k + rank_embedding) + 1/(k + rank_llm_score)

    Before this, scripts/rank_jobs.py chose the pool feeding rerank/listwise/
    debate purely by embedding rank — the scorer's LLM score was only ever used
    as a >min_score exclusion filter, never to influence ordering. A job scored
    9/10 by the LLM but with only average cosine similarity could sit outside
    the top-N and never reach the paid rerank/listwise stages at all.

    A job the LLM scorer hasn't reached yet (score=None) gets no LLM-rank
    contribution rather than a fabricated rank — it's still eligible purely on
    embedding rank, exactly as before this fusion existed."""
    if not jobs:
        return []

    by_embedding = sorted(
        jobs,
        key=lambda j: j.get("_embedding_score") if j.get("_embedding_score") is not None else float("-inf"),
        reverse=True,
    )
    embedding_rank = {job["id"]: i for i, job in enumerate(by_embedding)}

    scored = [j for j in jobs if j.get("score") is not None]
    by_llm_score = sorted(scored, key=lambda j: j["score"], reverse=True)
    llm_rank = {job["id"]: i for i, job in enumerate(by_llm_score)}

    def rrf_score(job: dict) -> float:
        total = 1.0 / (k + embedding_rank[job["id"]])
        if job["id"] in llm_rank:
            total += 1.0 / (k + llm_rank[job["id"]])
        return total

    return sorted(jobs, key=rrf_score, reverse=True)
