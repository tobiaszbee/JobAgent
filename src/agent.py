import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.stdout.reconfigure(line_buffering=True)

from src.browser import Browser
from src.evaluator import evaluate, load_examples
from src.db.migrations import run as init_db
from src.db.repositories import job_repository as jobs
from src.db.repositories import session_repository as sessions
from src.db.repositories.criteria_repository import get_criteria_dict
from src.import_examples import run as sync_examples


def run(days=7, max_jobs=None, titles=None, locations=None):
    init_db()

    criteria = get_criteria_dict()

    if titles:
        criteria["titles"] = titles
    if locations:
        criteria["locations"] = locations
    limit = max_jobs if max_jobs is not None else float('inf')

    session_id = sessions.start()
    jobs_found = 0
    jobs_new = 0
    jobs_scored = 0

    print("Starting Job Agent...")
    print(f"Search window: last {days} days")
    print(f"Job limit: {'unlimited' if max_jobs is None else max_jobs}")
    print(f"Titles: {', '.join(criteria['titles'])}")
    print(f"Locations: {', '.join(criteria['locations'])}")
    print("=" * 50)

    seconds = days * 24 * 3600
    search_params = f"&f_WT=2&f_TPR=r{seconds}"

    try:
        with Browser(extra_search_params=search_params) as browser:
            browser.wait_for_login()
            sync_examples(browser)

            examples = load_examples()

            for title in criteria["titles"]:
                if jobs_new >= limit:
                    break
                for location in criteria["locations"]:
                    if jobs_new >= limit:
                        break

                    print(f"\nSearching: {title} in {location}")
                    remaining = limit - jobs_new if max_jobs else None
                    found = browser.search_jobs(title, location, max_jobs=remaining)
                    jobs_found += len(found)

                    for job in found:
                        if jobs_new >= limit:
                            break

                        job_id = jobs.insert(
                            title=job["title"],
                            company=job["company"],
                            location=job["location"],
                            url=job["url"],
                            description=""
                        )

                        if job_id is None:
                            print(f"  Skipping (already seen): {job['title']}")
                            continue

                        jobs_new += 1
                        print(f"  New job ({jobs_new}{'/' + str(max_jobs) if max_jobs else ''}): {job['title']} @ {job['company']}")

            pending = jobs.get_pending_evaluation()
            print(f"\nFetching descriptions and evaluating {len(pending)} jobs...")

            for job in pending:
                print(f"\nEvaluating: {job['title']} @ {job['company']}")

                description = browser.get_job_description(job["url"])
                jobs.update_description(job["id"], description)
                job["description"] = description

                result = evaluate(job, criteria, examples)
                jobs.update_score(job["id"], result["score"], result["reasoning"])

                if result["dealbreakers_found"]:
                    jobs.update_status(job["id"], "auto_rejected")
                    print(f"  Auto-rejected — {result['dealbreakers_found']}")
                else:
                    print(f"  Score: {result['score']}/10 — {result['reasoning']}")

                jobs_scored += 1

        sessions.finish(session_id, jobs_found, jobs_new, jobs_scored)

        print("\n" + "=" * 50)
        print("Session complete!")
        print(f"  Jobs found:   {jobs_found}")
        print(f"  Jobs new:     {jobs_new}")
        print(f"  Jobs scored:  {jobs_scored}")

        top = jobs.get_top(min_score=6.0)
        if top:
            print(f"\nTop jobs (score >= 6.0):")
            for job in top[:5]:
                print(f"  {job['score']}/10 — {job['title']} @ {job['company']}")

    except Exception as e:
        sessions.finish(session_id, jobs_found, jobs_new, jobs_scored, status="failed")
        print(f"\nERROR: {e}")
        raise e


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",      type=int,   default=7,    help="Days back to search")
    parser.add_argument("--max-jobs",  type=int,   default=None, help="Max new jobs (default: unlimited)")
    parser.add_argument("--titles",    nargs="*",  default=None, help="Override titles")
    parser.add_argument("--locations", nargs="*",  default=None, help="Override locations")
    args = parser.parse_args()
    run(days=args.days, max_jobs=args.max_jobs, titles=args.titles, locations=args.locations)
