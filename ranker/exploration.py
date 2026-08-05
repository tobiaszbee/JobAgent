# Exploration slots: a handful of jobs outside the normal top-N pool get a
# real Opus + debate look anyway, since embedding similarity, RRF, and the
# cross-encoder rerank all share the same biases and a genuinely good but
# atypically-worded posting could otherwise get permanently buried without
# the ranking ever testing whether it's missing good jobs lower down.
#
# Distinct from FALLBACK_RANK_REASON/OMITTED_RANK_REASON (ranker/listwise.py),
# which mark a degraded run: an exploration pick gets full Opus + debate
# review, just tagged so the apply-rate-per-bucket metric can exclude it,
# since its rank reflects pool composition, not the pipeline's real judgment.
import hashlib
from datetime import date

EXPLORATION_RANK_REASON_PREFIX = "[EXPLORATION] "


def pick_exploration_slots(candidates: list[dict], count: int, seed_date: date | None = None) -> list[dict]:
    # Keyed by md5(date:job_id) so each job's selection depends only on the
    # date and its own id, never on which other candidates are present.
    # Repeated same-day runs pick the same jobs this way, which
    # ranker/rank_cache.py's reuse_if_unchanged depends on for its cache to
    # actually hit. A naive random.Random(date).sample(pool, k) doesn't give
    # this: sample() picks by index, so adding/removing any candidate shifts
    # every later index and can change the whole result.
    if not candidates or count <= 0:
        return []
    seed = (seed_date or date.today()).isoformat()
    ranked_by_key = sorted(candidates, key=lambda j: hashlib.md5(f"{seed}:{j['id']}".encode()).hexdigest())
    return ranked_by_key[:count]


def tag_exploration_picks(ranked_jobs: list[dict], exploration_ids: set[str]) -> None:
    # Mutates in place, prefixing rank_reason so exploration picks stay
    # greppable server-side (LIKE '[EXPLORATION]%') without losing Opus's
    # real reasoning underneath the prefix.
    for job in ranked_jobs:
        if job["id"] in exploration_ids:
            job["rank_reason"] = EXPLORATION_RANK_REASON_PREFIX + (job.get("rank_reason") or "")


def compute_non_exploration_ranks(ranked_jobs: list[dict], exploration_ids: set[str]) -> dict[str, int]:
    # 1-indexed rank among only the non-exploration jobs, preserving relative
    # listwise_rank order; exploration jobs are absent from the map entirely.
    # Gates ranker/would_apply.py's rank_ceiling: Opus/debate rank the
    # exploration-extended pool as one list, so an exploration pick landing
    # at #4 would otherwise push a real candidate from #10 to #11 and cost it
    # its would-apply slot. Exploration jobs getting no effective rank (and
    # so never being would-apply eligible) is deliberate: would-apply is a
    # live auto-apply gate, exploration's role is diagnostic.
    non_exploration = sorted(
        (j for j in ranked_jobs if j["id"] not in exploration_ids),
        key=lambda j: j["listwise_rank"],
    )
    return {j["id"]: i + 1 for i, j in enumerate(non_exploration)}
