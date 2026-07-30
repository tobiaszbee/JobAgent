"""Re-score all 'new' jobs using current preferences (overwrites existing scores safely)."""
import sys
import logging

sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

from db.repositories import job_repository
from evaluator.runner import run as evaluate

jobs = job_repository.get_new_with_descriptions()
if not jobs:
    print("No 'new' jobs with descriptions to re-score.")
    sys.exit(0)

print(f"Will re-score {len(jobs)} job(s) with current preferences...")
result = evaluate(force_rescore=True)
print(f"\nDone. Scored {result.get('jobs_scored', 0)} job(s).")
