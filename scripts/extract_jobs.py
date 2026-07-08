"""Backfill structured data extraction for all jobs that don't have it yet."""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.migrations import init_db
from db.repositories import job_repository
from extractor.runner import run_extraction

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

init_db()

jobs = job_repository.search(status="all")
pending = [j for j in jobs if j.get("description") and not j.get("structured_data")]
logger.info(f"Jobs to extract: {len(pending)} / {len(jobs)}")

if not pending:
    logger.info("Nothing to do.")
    sys.exit(0)

updated = run_extraction(pending)
logger.info(f"Done. Extracted: {updated}")
