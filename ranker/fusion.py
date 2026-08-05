import logging

logger = logging.getLogger(__name__)

# Standard IR default (Cormack et al., "Reciprocal Rank Fusion outperforms
# Condorcet and individual rank learning methods"), large enough that a
# single ranking's #1 vs #2 doesn't dominate the fused order, so a job that's
# merely good in both rankings can beat one that's #1 in one and mediocre in
# the other.
_RRF_K = 60


def fuse_by_rrf(jobs: list[dict], k: int = _RRF_K, extra_rank_field: str | None = None) -> list[dict]:
    # Reciprocal Rank Fusion over embedding similarity, the LLM scorer's
    # score, and optionally a third leg named by extra_rank_field:
    #   RRF_score(job) = 1/(k + rank_embedding) + 1/(k + rank_llm_score) [+ 1/(k + rank_extra)]
    # A job missing a leg's value gets no contribution from that leg rather
    # than a fabricated rank. The caller is responsible for skipping
    # extra_rank_field when ranker.reranker.rerank_jobs flagged the value as
    # unreliable (_rerank_unreliable), since this function has no way to
    # know that on its own.
    if not jobs:
        return []

    # Tie-broken by id, not left to sorted()'s stability: sorted() is stable, and
    # `jobs` arrives from scripts/rank_jobs.py already ordered by embedding score
    # descending, so without an explicit, embedding-independent tiebreaker, any
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
