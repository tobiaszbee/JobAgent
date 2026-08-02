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
import hashlib
from datetime import date

EXPLORATION_RANK_REASON_PREFIX = "[EXPLORATION] "


def pick_exploration_slots(candidates: list[dict], count: int, seed_date: date | None = None) -> list[dict]:
    """Picks `count` jobs from `candidates` (expected to be the ranking-eligible
    pool minus whatever already made the top-N), keyed by md5(date:job_id) so
    each job's selection depends only on the date and its own id — never on
    which other candidates happen to be present. Repeated same-day runs pick
    the same jobs — ranker/rank_cache.py's reuse_if_unchanged compares the
    exact listwise-pool job-id set between runs, and a different sample every
    single run would defeat that cache permanently (full Opus + debate cost
    every run, not just once per day when the exploration set actually
    rotates).

    A naive random.Random(date).sample(pool, k) does NOT give this guarantee:
    sample() picks by index, so removing or adding any candidate — even one
    that was never picked — shifts every later index and can change the whole
    result. Per-job keying is what makes the picks stable while the pool
    around them keeps changing (jobs get decided, new ones arrive) — the
    normal case, not an edge case, for a daily-run pipeline."""
    if not candidates or count <= 0:
        return []
    seed = (seed_date or date.today()).isoformat()
    ranked_by_key = sorted(candidates, key=lambda j: hashlib.md5(f"{seed}:{j['id']}".encode()).hexdigest())
    return ranked_by_key[:count]


def tag_exploration_picks(ranked_jobs: list[dict], exploration_ids: set[str]) -> None:
    """Mutates ranked_jobs in place, prefixing rank_reason for exploration
    picks. Keeps Opus's real reasoning (these still go through full listwise +
    debate review) while making the pick greppable server-side (LIKE
    '[EXPLORATION]%') for the apply-rate-per-bucket metric to exclude."""
    for job in ranked_jobs:
        if job["id"] in exploration_ids:
            job["rank_reason"] = EXPLORATION_RANK_REASON_PREFIX + (job.get("rank_reason") or "")


def compute_non_exploration_ranks(ranked_jobs: list[dict], exploration_ids: set[str]) -> dict[str, int]:
    """1-indexed rank among only the non-exploration jobs in ranked_jobs,
    preserving their relative listwise_rank order. Exploration jobs are
    entirely absent from the returned map.

    Used to gate ranker/would_apply.py's rank_ceiling: exploration extends the
    listwise pool rather than displacing real top-N candidates (see
    scripts/rank_jobs.py), but Opus/debate rank the extended pool as one list —
    an exploration pick landing at #4 would otherwise push a real candidate
    from #10 to #11 and cost it its would-apply slot, which is exactly the
    displacement extending was meant to avoid. Gating on the rank a job would
    have had with exploration picks removed closes that gap. Exploration jobs
    getting no effective rank (and therefore never being would-apply eligible
    themselves) is deliberate: would-apply is a live auto-apply gate,
    exploration's role is diagnostic, not conversion."""
    non_exploration = sorted(
        (j for j in ranked_jobs if j["id"] not in exploration_ids),
        key=lambda j: j["listwise_rank"],
    )
    return {j["id"]: i + 1 for i, j in enumerate(non_exploration)}
