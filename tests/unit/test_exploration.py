from datetime import date

from ranker.exploration import (
    EXPLORATION_RANK_REASON_PREFIX, compute_non_exploration_ranks, pick_exploration_slots, tag_exploration_picks,
)


def _job(id_):
    return {"id": id_}


def test_empty_candidates_returns_empty():
    assert pick_exploration_slots([], 3) == []


def test_zero_count_returns_empty():
    assert pick_exploration_slots([_job("a"), _job("b")], 0) == []


def test_picks_requested_count():
    candidates = [_job(str(i)) for i in range(10)]
    picks = pick_exploration_slots(candidates, 3, seed_date=date(2026, 8, 1))
    assert len(picks) == 3


def test_count_clamped_to_pool_size():
    candidates = [_job("a"), _job("b")]
    picks = pick_exploration_slots(candidates, 5, seed_date=date(2026, 8, 1))
    assert len(picks) == 2


def test_same_day_seed_picks_the_same_jobs():
    # The whole point: rank_cache.reuse_if_unchanged compares the exact
    # listwise-pool job-id set between runs, a different sample every run
    # would defeat that cache permanently.
    candidates = [_job(str(i)) for i in range(20)]
    day = date(2026, 8, 1)
    first = pick_exploration_slots(candidates, 3, seed_date=day)
    second = pick_exploration_slots(candidates, 3, seed_date=day)
    assert {j["id"] for j in first} == {j["id"] for j in second}


def test_different_day_seed_can_pick_different_jobs():
    candidates = [_job(str(i)) for i in range(20)]
    day1 = pick_exploration_slots(candidates, 3, seed_date=date(2026, 8, 1))
    day2 = pick_exploration_slots(candidates, 3, seed_date=date(2026, 8, 2))
    assert {j["id"] for j in day1} != {j["id"] for j in day2}


def test_selection_independent_of_input_order():
    # Per-job keying means a re-ordered (but same-membership) input list, e.g.
    # from run-to-run score jitter re-sorting `fused`, still yields the same
    # day's pick.
    candidates = [_job(str(i)) for i in range(20)]
    reversed_candidates = list(reversed(candidates))
    day = date(2026, 8, 1)
    a = pick_exploration_slots(candidates, 3, seed_date=day)
    b = pick_exploration_slots(reversed_candidates, 3, seed_date=day)
    assert {j["id"] for j in a} == {j["id"] for j in b}


def test_selection_stable_when_unpicked_candidates_leave_the_pool():
    # Regression: an earlier implementation sampled by INDEX
    # (random.Random(seed).sample(sorted_pool, k)), removing any candidate,
    # even one that was never picked, shifts every later index and can change
    # the whole result. The real pool changes every run (jobs get decided, new
    # ones arrive), so that instability would defeat rank_cache's
    # reuse_if_unchanged on nearly every run, not just once a day.
    candidates = [_job(str(i)) for i in range(20)]
    day = date(2026, 8, 1)
    first = pick_exploration_slots(candidates, 3, seed_date=day)
    picked_ids = {j["id"] for j in first}

    shrunk = [j for j in candidates if j["id"] not in picked_ids][2:]  # drop 2 unpicked candidates
    shrunk += [j for j in candidates if j["id"] in picked_ids]
    second = pick_exploration_slots(shrunk, 3, seed_date=day)

    assert {j["id"] for j in second} == picked_ids


def test_picks_are_a_subset_of_candidates():
    candidates = [_job(str(i)) for i in range(20)]
    picks = pick_exploration_slots(candidates, 3, seed_date=date(2026, 8, 1))
    candidate_ids = {j["id"] for j in candidates}
    assert all(j["id"] in candidate_ids for j in picks)


def test_tag_exploration_picks_prefixes_matching_jobs_only():
    ranked = [
        {"id": "a", "rank_reason": "Great fit for backend focus."},
        {"id": "b", "rank_reason": "Strong Python match."},
    ]
    tag_exploration_picks(ranked, {"a"})
    assert ranked[0]["rank_reason"] == EXPLORATION_RANK_REASON_PREFIX + "Great fit for backend focus."
    assert ranked[1]["rank_reason"] == "Strong Python match."


def test_tag_exploration_picks_handles_missing_rank_reason():
    ranked = [{"id": "a"}]
    tag_exploration_picks(ranked, {"a"})
    assert ranked[0]["rank_reason"] == EXPLORATION_RANK_REASON_PREFIX


def test_tag_exploration_picks_no_op_when_no_ids_match():
    ranked = [{"id": "a", "rank_reason": "Reason."}]
    tag_exploration_picks(ranked, {"other"})
    assert ranked[0]["rank_reason"] == "Reason."


def _ranked_job(id_, listwise_rank):
    return {"id": id_, "listwise_rank": listwise_rank}


def test_non_exploration_ranks_matches_listwise_rank_when_no_exploration():
    ranked = [_ranked_job("a", 1), _ranked_job("b", 2), _ranked_job("c", 3)]
    ranks = compute_non_exploration_ranks(ranked, set())
    assert ranks == {"a": 1, "b": 2, "c": 3}


def test_non_exploration_ranks_excludes_exploration_jobs_entirely():
    ranked = [_ranked_job("a", 1), _ranked_job("b", 2), _ranked_job("c", 3)]
    ranks = compute_non_exploration_ranks(ranked, {"b"})
    assert "b" not in ranks


def test_non_exploration_ranks_closes_the_gap_left_by_exploration_jobs():
    # Regression: an exploration pick landing ahead of a real candidate (e.g.
    # Opus genuinely liked it) must not push that candidate past
    # rank_ceiling, the pick extends the pool, it isn't supposed to cost a
    # real candidate its would-apply slot.
    ranked = [_ranked_job("explore", 1), _ranked_job("real1", 2), _ranked_job("real2", 3)]
    ranks = compute_non_exploration_ranks(ranked, {"explore"})
    assert ranks == {"real1": 1, "real2": 2}
