import sys
import os
import random
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import STEALTH
from db.migrations import init_db
from db.repositories import job_repository, session_repository, criteria_repository
from collector.filters import apply_filters
from collector.sources.linkedin import LinkedInSource


def _fetch_descriptions_in_batches(new_job_ids: list[tuple[str, str]], log=print) -> None:
    """
    Fetch descriptions for new jobs in small batches with fresh browser sessions
    and long pauses between batches to avoid LinkedIn rate-limiting.
    """
    batch_size = STEALTH["batch_size"]
    distract_every = STEALTH["distract_every_n_batches"]
    batches = [new_job_ids[i:i + batch_size] for i in range(0, len(new_job_ids), batch_size)]

    log(f"\nFetching descriptions in {len(batches)} batch(es) of ≤{batch_size}...")

    ok_total = 0
    fail_total = 0

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            pause = random.uniform(
                STEALTH["batch_pause_min"],
                STEALTH["batch_pause_max"],
            )
            log(f"\n[stealth] Pausing {pause / 60:.1f} min before batch {batch_idx + 1}/{len(batches)}...")
            time.sleep(pause)

        log(f"\n--- Batch {batch_idx + 1}/{len(batches)} ({len(batch)} jobs) ---")

        with LinkedInSource() as source:
            source.login()

            if distract_every > 0 and batch_idx > 0 and batch_idx % distract_every == 0:
                source.distract()

            ok = 0
            fail = 0
            for job_id, url in batch:
                desc = source.fetch_description(url)
                if desc:
                    job_repository.update_description(job_id, desc)
                    log(f"  OK: {url.split('/')[-2]}")
                    ok += 1
                else:
                    # One retry after a short extra wait
                    log(f"  Retry: {url.split('/')[-2]}")
                    time.sleep(random.uniform(30, 60))
                    desc = source.fetch_description(url)
                    if desc:
                        job_repository.update_description(job_id, desc)
                        log(f"  Retry OK")
                        ok += 1
                    else:
                        log(f"  Failed: {url}")
                        fail += 1

        log(f"  Batch {batch_idx + 1} done: {ok} OK, {fail} failed")
        ok_total += ok
        fail_total += fail

    log(f"\nDescriptions: {ok_total} fetched, {fail_total} still missing")


def run(
    days_back: int = 7,
    max_jobs: int | None = None,
    titles: list[str] | None = None,
    locations: list[str] | None = None,
    search_queries_override: list[str] | None = None,
    log=print,
) -> dict:
    init_db()

    criteria = criteria_repository.get_active_dict()
    if titles:
        criteria["titles"] = titles
    if locations:
        criteria["locations"] = locations
    if search_queries_override:
        criteria["search_queries"] = search_queries_override

    search_queries = criteria["search_queries"] or criteria["titles"]
    if not search_queries or not criteria["locations"]:
        raise ValueError("At least one search query (or job title) and one location must be configured before running the collector.")

    session_id = session_repository.start()
    jobs_found = 0
    jobs_new = 0

    log(f"Collector starting — last {days_back} day(s), limit: {max_jobs or 'unlimited'}")
    log(f"Search queries: {', '.join(search_queries)}")
    log(f"Locations:      {', '.join(criteria['locations'])}")
    log("=" * 50)

    try:
        # ── Phase 1: collect job cards (no description fetching) ──────────────
        new_job_ids: list[tuple[str, str]] = []

        with LinkedInSource(days_back=days_back) as source:
            source.login()

            first_search = True
            for title in search_queries:
                if max_jobs and jobs_new >= max_jobs:
                    break
                for location in criteria["locations"]:
                    if max_jobs and jobs_new >= max_jobs:
                        break

                    # Pause before each search except the first to avoid rate-limiting
                    if not first_search:
                        pause = random.uniform(
                            STEALTH["search_pause_min"],
                            STEALTH["search_pause_max"],
                        )
                        log(f"  [stealth] Pausing {pause:.0f}s before next search...")
                        time.sleep(pause)
                    first_search = False

                    log(f"\nSearching: {title!r} in {location!r}")
                    remaining = (max_jobs - jobs_new) if max_jobs else None
                    raw_jobs = source.search(title, location, max_results=remaining)
                    jobs_found += len(raw_jobs)

                    filtered = apply_filters(raw_jobs, criteria["rejected"])
                    skipped = len(raw_jobs) - len(filtered)
                    if skipped:
                        log(f"  Filtered out {skipped} job(s) by keyword")

                    for raw in filtered:
                        if max_jobs and jobs_new >= max_jobs:
                            break
                        job_id = job_repository.insert(
                            title=raw.title,
                            company=raw.company,
                            location=raw.location,
                            url=raw.url,
                            source=raw.source,
                            source_id=raw.source_id,
                        )
                        if job_id is None:
                            log(f"  Skip (duplicate): {raw.title} @ {raw.company}")
                            continue

                        jobs_new += 1
                        new_job_ids.append((job_id, raw.url))
                        log(f"  [{jobs_new}{'/' + str(max_jobs) if max_jobs else ''}] {raw.title} @ {raw.company}")

        # Browser closed here — short cooldown before opening again for descriptions
        if new_job_ids:
            cooldown = random.uniform(30, 90)
            log(f"\n[stealth] Cooldown {cooldown:.0f}s before fetching descriptions...")
            time.sleep(cooldown)
            _fetch_descriptions_in_batches(new_job_ids, log=log)

        session_repository.finish(session_id, jobs_found=jobs_found, jobs_scored=0)

        log("\n" + "=" * 50)
        log(f"Done. Found: {jobs_found}  New: {jobs_new}")

        return {"jobs_found": jobs_found, "jobs_new": jobs_new}

    except Exception as e:
        session_repository.finish(session_id, jobs_found=jobs_found, jobs_scored=0, status="error")
        log(f"\nERROR: {e}")
        raise


if __name__ == "__main__":
    import argparse

    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description="Collect job listings from LinkedIn")
    parser.add_argument("--days",           type=int,  default=7,    help="Days back to search (default: 7)")
    parser.add_argument("--max-jobs",       type=int,  default=None, help="Max new jobs to collect (default: unlimited)")
    parser.add_argument("--titles",         nargs="*", default=None, help="Override job titles (scoring only)")
    parser.add_argument("--locations",      nargs="*", default=None, help="Override search locations")
    parser.add_argument("--search-queries", nargs="*", default=None, help="Override LinkedIn search queries")
    args = parser.parse_args()

    run(
        days_back=args.days,
        max_jobs=args.max_jobs,
        titles=args.titles,
        locations=args.locations,
        search_queries_override=args.search_queries,
    )
