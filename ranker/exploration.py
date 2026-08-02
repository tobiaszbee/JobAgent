"""Exploration slots: a handful of jobs outside the normal top-N pool get a
real Opus + debate look anyway, on the theory that embedding similarity, RRF,
and the cross-encoder rerank all share the same biases (e.g. underweighting a
genuinely good but atypically-worded posting) — a job that's a real fit can
get permanently buried without ever reaching a human-quality read. Without
this, the ranking can only ever validate itself: it never tests whether it's
systematically missing good jobs lower down.

Distinct from FALLBACK_RANK_REASON/OMITTED_RANK_REASON (ranker/listwise.py):
those mark a degraded run where Opus's real judgment is missing or partial.
An exploration pick DOES get full Opus + debate review — it's tagged so the
apply-rate-per-bucket metric (JobAgentWeb routers/evaluation.py) can exclude
it, since its rank reflects pool composition (a randomly injected outsider),
not the normal deterministic pipeline's judgment.
"""
import random
from datetime import date

EXPLORATION_RANK_REASON_PREFIX = "[EXPLORATION] "


def pick_exploration_slots(candidates: list[dict], count: int, seed_date: date | None = None) -> list[dict]:
    """Randomly samples `count` jobs from `candidates` (expected to be the
    ranking-eligible pool minus whatever already made the top-N). Seeded by the
    calendar date, not per-run, so repeated runs on the same day pick the same
    jobs — ranker/rank_cache.py's reuse_if_unchanged compares the exact
    listwise-pool job-id set between runs, and a different random sample every
    single run would defeat that cache permanently (full Opus + debate cost
    every run, not just once per day when the exploration set actually
    rotates). Candidates are sorted by id before sampling so the pick doesn't
    depend on the incoming list's order, which can vary run-to-run even when
    the underlying pool is the same. This is best-effort day-stability, not a
    hard guarantee — if the candidate pool's membership itself changes
    intraday (a candidate gets decided, or a new job arrives and displaces the
    top-N cutoff), the sample can still shift before the day rolls over."""
    if not candidates or count <= 0:
        return []
    seed_date = seed_date or date.today()
    pool = sorted(candidates, key=lambda j: j["id"])
    rng = random.Random(seed_date.isoformat())
    return rng.sample(pool, min(count, len(pool)))


def tag_exploration_picks(ranked_jobs: list[dict], exploration_ids: set[str]) -> None:
    """Mutates ranked_jobs in place, prefixing rank_reason for exploration
    picks. Keeps Opus's real reasoning (these still go through full listwise +
    debate review) while making the pick greppable server-side (LIKE
    '[EXPLORATION]%') for the apply-rate-per-bucket metric to exclude."""
    for job in ranked_jobs:
        if job["id"] in exploration_ids:
            job["rank_reason"] = EXPLORATION_RANK_REASON_PREFIX + (job.get("rank_reason") or "")
