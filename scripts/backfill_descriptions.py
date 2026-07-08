"""Retry fetching descriptions for jobs that are missing them (batched, stealth-safe)."""
import sys
import random
import time
from datetime import datetime, timedelta

from config import STEALTH
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

print(f"Found {total} job(s) without descriptions. Fetching in batches...")
print(f"PROGRESS:0/{total}")

batch_size    = STEALTH["batch_size"]
distract_ev   = STEALTH["distract_every_n_batches"]
batches       = [missing[i:i + batch_size] for i in range(0, total, batch_size)]
done = ok = failed = 0

for batch_idx, batch in enumerate(batches):
    if batch_idx > 0:
        pause = random.uniform(STEALTH["batch_pause_min"], STEALTH["batch_pause_max"])
        resume = (datetime.now() + timedelta(seconds=pause)).strftime("%H:%M")
        print(f"\n[stealth] Pausing {pause / 60:.1f} min before batch {batch_idx + 1}/{len(batches)}... → resume ~{resume}")
        time.sleep(pause)

    print(f"\n--- Batch {batch_idx + 1}/{len(batches)} ({len(batch)} jobs) ---")

    with LinkedInSource() as source:
        source.login()

        if distract_ev > 0 and batch_idx > 0 and batch_idx % distract_ev == 0:
            source.distract()

        for job in batch:
            desc = source.fetch_description(job["url"])
            if desc:
                job_repository.update_description(job["id"], desc)
                print(f"  OK ({len(desc)} chars): {job['url'].split('/')[-2]}")
                ok += 1
            else:
                print(f"  Retry: {job['url'].split('/')[-2]}")
                time.sleep(random.uniform(30, 60))
                desc = source.fetch_description(job["url"])
                if desc:
                    job_repository.update_description(job["id"], desc)
                    print(f"  Retry OK")
                    ok += 1
                else:
                    print(f"  Failed (unavailable): {job['url']}")
                    job_repository.update_score_and_status(job["id"], 0.0, "Job listing no longer available on LinkedIn", "auto_rejected")
                    failed += 1

            done += 1
            print(f"PROGRESS:{done}/{total}")

print(f"\nDone. Fetched: {ok}  Still missing: {failed}")
