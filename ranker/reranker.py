import logging
from embeddings.client import VoyageClient

logger = logging.getLogger(__name__)

_client: VoyageClient | None = None


def _get_client() -> VoyageClient:
    global _client
    if _client is None:
        _client = VoyageClient()
    return _client


def rerank_jobs(jobs: list[dict], query: str, top_k: int = 20) -> list[dict]:
    """
    Cross-encoder rerank using Voyage Rerank API.
    Returns up to top_k jobs sorted by rerank score (best first).
    Falls back to original order on failure.
    """
    if not jobs:
        return []

    client = _get_client()
    query_text = (query or "software engineer developer")[:500]

    documents = []
    for job in jobs:
        desc = (job.get("description") or "")[:1000].replace("\n", " ")
        documents.append(f"{job['title']} at {job['company']}\n{desc}")

    try:
        results = client.rerank(query=query_text, documents=documents, top_k=min(top_k, len(documents)))
    except Exception as e:
        logger.error(f"Voyage rerank failed: {e} — falling back to embedding order")
        for job in jobs:
            job.setdefault("rerank_score", job.get("_embedding_score", 0.0))
        return jobs[:top_k]

    try:
        from db.repositories.usage_repository import log_voyage_rerank
        log_voyage_rerank(len(documents))
    except Exception:
        pass

    reranked = []
    for r in results:
        reranked.append({**jobs[r["index"]], "rerank_score": r["score"]})

    return reranked
