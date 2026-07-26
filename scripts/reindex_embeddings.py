"""Recompute embeddings for every job that already has one. Needed whenever
embeddings/indexer.py's _job_to_text() changes (e.g. the 2026-07-25 fix that routed
it through collector.utils.build_excerpt so LinkedIn page-chrome junk no longer
pollutes the embedded text) — job_embeddings rows written before such a fix keep the
old, stale vector until explicitly recomputed; index_jobs()'s normal call sites only
embed jobs that don't have a row yet."""
import sys

from db.connection import get_connection
from db.migrations import init_db
from embeddings.indexer import index_jobs

sys.stdout.reconfigure(line_buffering=True)

init_db()

conn = get_connection()
rows = conn.execute("""
    SELECT j.id, j.title, j.company, j.location, j.description, j.source
    FROM jobs j
    JOIN job_embeddings je ON je.job_id = j.id
""").fetchall()
conn.close()

jobs = [dict(r) for r in rows]
total = len(jobs)

if not total:
    print("No embedded jobs to reindex.")
    sys.exit(0)

print(f"Reindexing {total} job(s) with an existing embedding...")
indexed = index_jobs(jobs)
print(f"\nDone. Reindexed: {indexed}/{total}")
