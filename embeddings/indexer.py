import json
import logging
import time

from config import VOYAGE_EMBED_MODEL
from db.connection import get_connection
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
    if job.get("description"):
        parts.append(job["description"][:2000])
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
    """Embed jobs and store in job_embeddings. Returns count indexed."""
    if not jobs:
        return 0

    client = _get_client()
    indexed = 0
    conn = get_connection()
    n = len(jobs)

    try:
        for i in range(0, n, BATCH_SIZE):
            batch = jobs[i:i + BATCH_SIZE]
            texts = [_job_to_text(j) for j in batch]
            embeddings = _embed_with_retry(client, texts)

            for job, emb in zip(batch, embeddings):
                conn.execute(
                    "INSERT OR REPLACE INTO job_embeddings (job_id, embedding, model) VALUES (?, ?, ?)",
                    (job["id"], json.dumps(emb), VOYAGE_EMBED_MODEL),
                )
                indexed += 1

            conn.commit()
            done = min(i + BATCH_SIZE, n)
            logger.info(f"  Indexed {done}/{n} jobs")

            if done < n:
                time.sleep(BATCH_DELAY)

    finally:
        conn.close()

    return indexed


def build_ideal_vector() -> list[float] | None:
    """
    Compute the 'ideal job' embedding vector:
    centroid(applied) - 0.3 × centroid(rejected)
    Returns None if no applied jobs are embedded yet.
    """
    conn = get_connection()
    try:
        applied_rows = conn.execute("""
            SELECT je.embedding FROM job_embeddings je
            JOIN jobs j ON j.id = je.job_id
            WHERE j.status = 'applied'
        """).fetchall()

        if not applied_rows:
            return None

        applied_vecs = [json.loads(r["embedding"]) for r in applied_rows]
        dim = len(applied_vecs[0])
        centroid_a = [sum(v[i] for v in applied_vecs) / len(applied_vecs) for i in range(dim)]

        rejected_rows = conn.execute("""
            SELECT je.embedding FROM job_embeddings je
            JOIN jobs j ON j.id = je.job_id
            WHERE j.status = 'rejected'
        """).fetchall()

        if not rejected_rows:
            return centroid_a

        rejected_vecs = [json.loads(r["embedding"]) for r in rejected_rows]
        centroid_r = [sum(v[i] for v in rejected_vecs) / len(rejected_vecs) for i in range(dim)]

        return [centroid_a[i] - 0.3 * centroid_r[i] for i in range(dim)]

    finally:
        conn.close()


def score_by_similarity(job_ids: list[str], ideal: list[float]) -> dict[str, float]:
    """Return cosine similarity for each job_id against the ideal vector."""
    if not job_ids or not ideal:
        return {}

    client = _get_client()
    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(job_ids))
        rows = conn.execute(
            f"SELECT job_id, embedding FROM job_embeddings WHERE job_id IN ({placeholders})",
            job_ids,
        ).fetchall()
    finally:
        conn.close()

    return {r["job_id"]: client.cosine_similarity(ideal, json.loads(r["embedding"])) for r in rows}
