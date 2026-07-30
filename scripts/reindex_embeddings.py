"""Recompute embeddings for every job that already has one. Needed whenever
embeddings/indexer.py's _job_to_text() changes (e.g. the 2026-07-25 fix that routed
it through collector.utils.build_excerpt so LinkedIn page-chrome junk no longer
pollutes the embedded text) — job_embeddings rows written before such a fix keep the
old, stale vector until explicitly recomputed; index_jobs()'s normal call sites only
embed jobs that don't have a row yet."""
import sys

import api_client
from embeddings.indexer import index_jobs

sys.stdout.reconfigure(line_buffering=True)

jobs = api_client.get("/api/embeddings/all-indexed").json()
total = len(jobs)

if not total:
    print("No embedded jobs to reindex.")
    sys.exit(0)

print(f"Reindexing {total} job(s) with an existing embedding...")
indexed = index_jobs(jobs)
print(f"\nDone. Reindexed: {indexed}/{total}")
