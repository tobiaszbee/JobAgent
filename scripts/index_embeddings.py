"""
One-time migration script: embed all existing jobs that have descriptions but no embedding yet.
Run this after setting up Voyage AI to backfill the embedding index.
"""
import sys
import logging

sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

from db.migrations import init_db
from db.connection import get_connection
from embeddings.indexer import index_jobs

init_db()
conn = get_connection()

rows = conn.execute("""
    SELECT j.id, j.title, j.company, j.location, j.description
    FROM jobs j
    LEFT JOIN job_embeddings je ON je.job_id = j.id
    WHERE j.description IS NOT NULL AND j.description != ''
      AND je.job_id IS NULL
    ORDER BY j.created_at DESC
""").fetchall()
conn.close()

if not rows:
    print("All jobs are already indexed.")
    sys.exit(0)

print(f"Indexing {len(rows)} job(s)...")
jobs = [dict(r) for r in rows]
indexed = index_jobs(jobs)
print(f"\nDone. Indexed {indexed} job(s).")
