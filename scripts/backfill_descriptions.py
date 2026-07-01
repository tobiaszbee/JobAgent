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
total = len(missing)

if not total:
    print("No jobs with missing descriptions.")
    print("PROGRESS:0/0")
    sys.exit(0)

print(f"Found {total} job(s) without a description. Fetching...")
print(f"PROGRESS:0/{total}")

ok = 0
failed = 0

with LinkedInSource() as source:
    source.login()
    for i, job in enumerate(missing, 1):
        desc = source.fetch_description(job["url"])
        if desc:
            job_repository.update_description(job["id"], desc)
            print(f"  [{i}/{total}] OK ({len(desc)} chars)")
            ok += 1
        else:
            print(f"  [{i}/{total}] No description: {job['url']}")
            failed += 1
        print(f"PROGRESS:{i}/{total}")

print(f"\nDone. Updated: {ok}  Still missing: {failed}")
