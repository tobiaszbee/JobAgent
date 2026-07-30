"""
One-time migration script: embed all existing jobs that have descriptions but no embedding yet.
Run this after setting up Voyage AI to backfill the embedding index.
"""
import sys
import logging

sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

import api_client
from embeddings.indexer import index_jobs

rows = api_client.get("/api/embeddings/unindexed").json()

if not rows:
    print("All jobs are already indexed.")
    sys.exit(0)

print(f"Indexing {len(rows)} job(s)...")
indexed = index_jobs(rows)
print(f"\nDone. Indexed {indexed} job(s).")
