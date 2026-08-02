from ranker.rank_cache import reuse_if_unchanged


def test_empty_pool_returns_empty_list():
    assert reuse_if_unchanged([], []) == []


def test_returns_none_when_never_ranked_before():
    listwise_pool = [{"id": "a"}, {"id": "b"}]
    previous_jobs = [{"id": "a", "listwise_rank": None}, {"id": "b", "listwise_rank": None}]
    assert reuse_if_unchanged(listwise_pool, previous_jobs) is None


def test_returns_none_when_pool_membership_changed():
    listwise_pool = [{"id": "a"}, {"id": "c"}]
    previous_jobs = [
        {"id": "a", "listwise_rank": 1},
        {"id": "b", "listwise_rank": 2},
        {"id": "c", "listwise_rank": None},
    ]
    assert reuse_if_unchanged(listwise_pool, previous_jobs) is None


def test_reuses_and_sorts_by_previous_listwise_rank_when_pool_unchanged():
    listwise_pool = [
        {"id": "b", "listwise_rank": 2, "rank_reason": "second"},
        {"id": "a", "listwise_rank": 1, "rank_reason": "first"},
    ]
    previous_jobs = [
        {"id": "a", "listwise_rank": 1},
        {"id": "b", "listwise_rank": 2},
    ]
    result = reuse_if_unchanged(listwise_pool, previous_jobs)
    assert [j["id"] for j in result] == ["a", "b"]


def test_previous_top_set_larger_than_current_pool_invalidates_cache():
    listwise_pool = [{"id": "a", "listwise_rank": 1}]
    previous_jobs = [
        {"id": "a", "listwise_rank": 1},
        {"id": "z", "listwise_rank": 5},
    ]
    assert reuse_if_unchanged(listwise_pool, previous_jobs) is None
