"""Retry fetching descriptions for jobs that are missing them."""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.migrations import init_db
from db.repositories import job_repository
from collector.sources.linkedin import LinkedInSource

sys.stdout.reconfigure(line_buffering=True)

init_db()
missing = job_repository.get_missing_descriptions()

if not missing:
    print("No jobs with missing descriptions.")
    sys.exit(0)

print(f"Found {len(missing)} job(s) without a description. Fetching...")

ok = 0
failed = 0

with LinkedInSource() as source:
    source.login()
    for i, job in enumerate(missing, 1):
        print(f"[{i}/{len(missing)}] {job['url']}")
        desc = source.fetch_description(job["url"])
        if desc:
            job_repository.update_description(job["id"], desc)
            print(f"  OK ({len(desc)} chars)")
            ok += 1
        else:
            print(f"  No description found")
            failed += 1

print(f"\nDone. Updated: {ok}  Still missing: {failed}")
