import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.migrations import init_db
from db.repositories import job_repository, session_repository, criteria_repository
from collector.filters import apply_filters
from collector.sources.linkedin import LinkedInSource


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
        with LinkedInSource(days_back=days_back) as source:
            source.login()

            new_job_ids: list[tuple[str, str]] = []  # (job_id, url)

            for title in search_queries:
                if max_jobs and jobs_new >= max_jobs:
                    break
                for location in criteria["locations"]:
                    if max_jobs and jobs_new >= max_jobs:
                        break

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

            if new_job_ids:
                log(f"\nFetching descriptions for {len(new_job_ids)} new job(s)...")
                for job_id, url in new_job_ids:
                    description = source.fetch_description(url)
                    if description:
                        job_repository.update_description(job_id, description)

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
