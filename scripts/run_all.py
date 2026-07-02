"""
Full pipeline: collect new jobs from LinkedIn, then score them with Claude.

Usage:
    python scripts/run_all.py
    python scripts/run_all.py --days 3 --max-jobs 30
    python scripts/run_all.py --log-file data/logs/run.log
"""
# -*- coding: utf-8 -*-
import argparse
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from collector.runner import run as collect
from evaluator.runner import run as evaluate


def _make_log(log_path: str | None):
    current_log = os.path.join(ROOT, "data", "logs", "current_run.log")
    os.makedirs(os.path.join(ROOT, "data", "logs"), exist_ok=True)
    current_fh = open(current_log, "w", encoding="utf-8")
    user_fh = open(log_path, "a", encoding="utf-8") if log_path else None

    def log(msg: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}" if msg.strip() else msg
        print(line)
        current_fh.write(line + "\n")
        current_fh.flush()
        if user_fh:
            user_fh.write(line + "\n")
            user_fh.flush()

    return log, (current_fh, user_fh)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full JobAgent pipeline: collect then evaluate")
    parser.add_argument("--days",           type=int,  default=1,    help="Days back to search (default: 1)")
    parser.add_argument("--max-jobs",       type=int,  default=None, help="Max new jobs to collect (default: unlimited)")
    parser.add_argument("--titles",         nargs="*", default=None, help="Override job titles (scoring only)")
    parser.add_argument("--search-queries", nargs="*", default=None, help="Override LinkedIn search queries")
    parser.add_argument("--locations",      nargs="*", default=None, help="Override search locations")
    parser.add_argument("--log-file",       default=None,            help="Append output to this file (e.g. data/logs/run.log)")
    parser.add_argument("--random-start",   type=int,  default=0,    help="Sleep random(0, N) seconds before starting (scheduler jitter)")
    args = parser.parse_args()

    log, fh = _make_log(args.log_file)

    try:
        if args.random_start > 0:
            import random
            delay = random.randint(0, args.random_start)
            log(f"[stealth] Random startup delay: {delay // 60}m {delay % 60}s")
            import time; time.sleep(delay)

        log(f"{'=' * 60}")
        log(f"JobAgent run started — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        log(f"{'=' * 60}")

        log("\n=== COLLECTOR ===")
        try:
            c_result = collect(
                days_back=args.days,
                max_jobs=args.max_jobs,
                titles=args.titles,
                search_queries_override=args.search_queries,
                locations=args.locations,
                log=log,
            )
        except Exception as e:
            log(f"\nCollector failed: {e}")
            log("Skipping evaluator.")
            return 1

        log(f"\nCollector result: found={c_result['jobs_found']}  new={c_result['jobs_new']}")

        log("\n=== EVALUATOR ===")
        try:
            e_result = evaluate(log=log)
        except Exception as e:
            log(f"\nEvaluator failed: {e}")
            return 1

        log(f"\nEvaluator result: scored={e_result['jobs_scored']}  auto_rejected={e_result['auto_rejected']}")
        log(f"\n{'=' * 60}")
        log("Run complete.")
        return 0

    finally:
        current_fh, user_fh = fh
        current_fh.close()
        if user_fh:
            user_fh.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
