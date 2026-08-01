"""Recompute embeddings for every job that already has one. Needed whenever
embeddings/indexer.py's _job_to_text() changes (e.g. the 2026-07-25 fix that routed
it through collector.utils.build_excerpt so LinkedIn page-chrome junk no longer
pollutes the embedded text) — job_embeddings rows written before such a fix keep the
old, stale vector until explicitly recomputed; index_jobs()'s normal call sites only
embed jobs that don't have a row yet.

Usage:
    python scripts/reindex_embeddings.py
    python scripts/reindex_embeddings.py --yes   # skip the confirmation prompt
"""
import argparse
import sys

import api_client
from config import MODEL_COSTS, VOYAGE_EMBED_MODEL
from embeddings.indexer import index_jobs

sys.stdout.reconfigure(line_buffering=True)

_EST_TOKENS_PER_JOB = 500  # title + up to ~2000-char description excerpt


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute embeddings for every already-indexed job")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    jobs = api_client.get("/api/embeddings/all-indexed").json()
    total = len(jobs)

    if not total:
        print("No embedded jobs to reindex.")
        return 0

    input_rate = MODEL_COSTS.get(VOYAGE_EMBED_MODEL, (0.0, 0.0))[0]
    est_cost = total * _EST_TOKENS_PER_JOB * input_rate / 1_000_000
    print(f"{total} job(s) have an existing embedding (est. cost ${est_cost:.2f}).")

    if not args.yes:
        reply = input("Re-embed all of them? [y/N] ").strip().lower()
        if reply != "y":
            print("Aborted.")
            return 1

    print(f"Reindexing {total} job(s)...")
    indexed = index_jobs(jobs)
    print(f"\nDone. Reindexed: {indexed}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
