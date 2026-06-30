import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.migrations import init_db
from db.repositories import job_repository, criteria_repository
from evaluator.scorer import score_job, build_system_prompt
from evaluator.profile import load_active_profile


def run(log=print) -> dict:
    init_db()

    pending = job_repository.get_unscored()
    if not pending:
        log("No unscored jobs to evaluate.")
        return {"jobs_scored": 0, "auto_rejected": 0}

    try:
        candidate_profile = load_active_profile()
    except ValueError as e:
        log(f"ERROR: {e}")
        return {"jobs_scored": 0, "auto_rejected": 0}

    criteria = criteria_repository.get_active_dict()
    positive_examples, negative_examples = job_repository.get_examples()

    # Build the system prompt once — it's identical for every job in this batch.
    system_prompt = build_system_prompt(criteria, positive_examples, negative_examples, candidate_profile)

    log(f"Evaluating {len(pending)} job(s)...")
    log(f"Few-shot: {len(positive_examples)} applied, {len(negative_examples)} rejected")
    log("=" * 50)

    jobs_scored = 0
    auto_rejected = 0

    for job in pending:
        log(f"\n[{jobs_scored + 1}/{len(pending)}] {job['title']} @ {job['company']}")

        result = score_job(
            job=job,
            system_prompt=system_prompt,
            log=log,
        )

        if result["dealbreakers_found"]:
            job_repository.update_score_and_status(
                job["id"], result["score"], result["score_reason"], "auto_rejected"
            )
            auto_rejected += 1
            log(f"  Auto-rejected: {result['dealbreakers_found']}")
        else:
            job_repository.update_score(job["id"], result["score"], result["score_reason"])
            log(f"  Score: {result['score']}/10 — {result['score_reason']}")

        jobs_scored += 1

    log("\n" + "=" * 50)
    log(f"Done. Scored: {jobs_scored}  Auto-rejected: {auto_rejected}")

    return {"jobs_scored": jobs_scored, "auto_rejected": auto_rejected}


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    run()
