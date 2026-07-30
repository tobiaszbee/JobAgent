import logging
import time

from config import VOYAGE_EMBED_MODEL
from collector.utils import build_excerpt
import api_client
from embeddings.client import VoyageClient

logger = logging.getLogger(__name__)

_client: VoyageClient | None = None

BATCH_SIZE = 128  # Voyage API max; safe at 600 RPM
BATCH_DELAY = 1   # seconds between batches (paid tier; increase to 22 if still on free tier)


def _get_client() -> VoyageClient:
    global _client
    if _client is None:
        _client = VoyageClient()
    return _client


def _job_to_text(job: dict) -> str:
    parts = [f"{job['title']} at {job['company']}"]
    if job.get("location"):
        parts.append(f"Location: {job['location']}")
    excerpt = build_excerpt(job.get("description"), job.get("source"))
    if excerpt:
        parts.append(excerpt[:2000])
    return "\n".join(parts)


def _embed_with_retry(client: VoyageClient, texts: list[str], max_retries: int = 6) -> list:
    """Embed with exponential-backoff retry for rate-limit errors."""
    for attempt in range(max_retries):
        try:
            return client.embed(texts)
        except Exception as e:
            msg = str(e).lower()
            if "rate" in msg or "429" in msg or "limit" in msg:
                wait = max(22, BATCH_DELAY) * (2 ** min(attempt, 3))
                logger.warning(f"  Rate limit hit (attempt {attempt+1}), waiting {wait:.0f}s…")
                time.sleep(wait)
            else:
                raise
    return client.embed(texts)  # final attempt — let it raise


def index_jobs(jobs: list[dict]) -> int:
    """Embed jobs and store in job_embeddings (shared across every user). Returns count indexed."""
    if not jobs:
        return 0

    client = _get_client()
    indexed = 0
    n = len(jobs)

    for i in range(0, n, BATCH_SIZE):
        batch = jobs[i:i + BATCH_SIZE]
        texts = [_job_to_text(j) for j in batch]
        embeddings = _embed_with_retry(client, texts)

        api_client.post("/api/embeddings", json={
            "items": [
                {"job_id": job["id"], "embedding": emb, "model": VOYAGE_EMBED_MODEL}
                for job, emb in zip(batch, embeddings)
            ],
        })
        indexed += len(batch)

        done = min(i + BATCH_SIZE, n)
        logger.info(f"  Indexed {done}/{n} jobs")

        if done < n:
            time.sleep(BATCH_DELAY)

    return indexed


def build_ideal_vector(candidate_profile: str | None = None) -> list[float] | None:
    """
    Compute the 'ideal job' embedding vector:
    centroid(applied) - 0.3 × centroid(rejected)

    Falls back to embedding `candidate_profile` (the CV summary) as a query vector when
    there's no applied-job history yet. Without this fallback, a new candidate's semantic
    retrieval step is skipped entirely (this function returned None) and the top-N pool
    reaching the paid rerank/listwise stages ends up ordered by scrape recency, not by
    fit — i.e. every new candidate's first run was scored on an essentially arbitrary
    slice of the pool. Returns None only when there's truly nothing to build a vector
    from (no applied jobs and no candidate profile).
    """
    vectors = api_client.get("/api/embeddings/decision-vectors").json()
    applied_vecs = vectors["applied"]

    if not applied_vecs:
        if not candidate_profile:
            return None
        client = _get_client()
        [vec] = client.embed([candidate_profile], input_type="query")
        return vec

    dim = len(applied_vecs[0])
    centroid_a = [sum(v[i] for v in applied_vecs) / len(applied_vecs) for i in range(dim)]

    rejected_vecs = vectors["rejected"]
    if not rejected_vecs:
        return centroid_a

    centroid_r = [sum(v[i] for v in rejected_vecs) / len(rejected_vecs) for i in range(dim)]
    return [centroid_a[i] - 0.3 * centroid_r[i] for i in range(dim)]


def score_by_similarity(job_ids: list[str], ideal: list[float]) -> dict[str, float]:
    """Return cosine similarity for each job_id against the ideal vector."""
    if not job_ids or not ideal:
        return {}

    client = _get_client()
    vectors = api_client.post("/api/embeddings/vectors", json={"job_ids": job_ids}).json()
    return {job_id: client.cosine_similarity(ideal, vec) for job_id, vec in vectors.items()}
