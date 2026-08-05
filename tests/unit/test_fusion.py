from ranker.fusion import fuse_by_rrf


def _job(id_, embedding_score=None, score=None, rerank_score=None):
    return {"id": id_, "_embedding_score": embedding_score, "score": score, "rerank_score": rerank_score}


def test_empty_input_returns_empty():
    assert fuse_by_rrf([]) == []


def test_pure_embedding_order_preserved_when_no_llm_scores():
    jobs = [_job("a", 0.5), _job("b", 0.9), _job("c", 0.1)]
    result = fuse_by_rrf(jobs)
    assert [j["id"] for j in result] == ["b", "a", "c"]


def test_unscored_job_ranked_purely_by_embedding():
    jobs = [_job("a", embedding_score=0.9, score=None), _job("b", embedding_score=0.1, score=None)]
    result = fuse_by_rrf(jobs)
    assert [j["id"] for j in result] == ["a", "b"]


def test_scored_job_can_outrank_unscored_job_with_better_embedding():
    jobs = [
        _job("a", embedding_score=0.9, score=None),
        _job("b", embedding_score=0.1, score=9.5),
    ]
    result = fuse_by_rrf(jobs)
    assert result[0]["id"] == "b"


def test_missing_embedding_score_does_not_crash():
    jobs = [_job("a", embedding_score=None, score=8.0), _job("b", embedding_score=0.9, score=None)]
    result = fuse_by_rrf(jobs)
    assert {j["id"] for j in result} == {"a", "b"}


def test_high_llm_score_job_moves_into_top_n_pool_despite_mediocre_embedding():
    # Regression: this is the exact audit scenario, a job the LLM scorer rated
    # 9.5/10 but with only mid-pack cosine similarity used to sit outside the
    # top-N pool entirely, since scripts/rank_jobs.py chose that pool by pure
    # embedding-rank truncation. The scorer's score was only ever an exclusion
    # filter (score > min_score), never an ordering signal.
    fillers = [_job(f"filler{i}", embedding_score=0.9 - i * 0.01, score=None) for i in range(10)]
    target = _job("target", embedding_score=0.5, score=9.5)
    jobs = fillers + [target]

    # Prove the old behavior would have excluded it from a top-5 pool.
    by_embedding_only = sorted(jobs, key=lambda j: j["_embedding_score"], reverse=True)
    assert target not in by_embedding_only[:5]

    fused = fuse_by_rrf(jobs)
    assert fused[0]["id"] == "target"
    assert target in fused[:5]


def test_score_ties_are_broken_by_id_not_input_order():
    # Regression: sorted() is stable, and jobs arrives pre-sorted by embedding
    # score (scripts/rank_jobs.py), so a tie on *either* leg used to keep
    # whatever relative order the input happened to be in, rather than an
    # embedding-independent tiebreak. With every job tied on both legs here,
    # the only thing that should decide the final order is id, reordering the
    # input must not change the result.
    a = _job("a", embedding_score=0.5, score=7.0)
    b = _job("b", embedding_score=0.5, score=7.0)
    c = _job("c", embedding_score=0.5, score=7.0)

    result_forward = fuse_by_rrf([a, b, c])
    result_backward = fuse_by_rrf([c, b, a])

    assert [j["id"] for j in result_forward] == [j["id"] for j in result_backward]


def test_score_tie_does_not_inherit_embedding_leg_order():
    # Three jobs tied on score, but with distinct (and reverse-of-id-order)
    # embedding scores, arriving pre-sorted by embedding (highest first),
    # exactly the shape scripts/rank_jobs.py produces. The old bug made the
    # LLM leg silently copy this same embedding order for the tied group,
    # so the fused result was just pure embedding order, as if the tied
    # LLM leg contributed nothing at all. With an independent tiebreak, the
    # two legs disagree on the tied group's order, so highest-embedding
    # should not simply win outright over lowest-embedding.
    high = _job("a", embedding_score=0.9, score=7.0)
    mid = _job("b", embedding_score=0.5, score=7.0)
    low = _job("z", embedding_score=0.1, score=7.0)

    result = fuse_by_rrf([high, mid, low])  # pre-sorted by embedding, as the real caller does

    assert [j["id"] for j in result] != ["a", "b", "z"]


def test_returns_new_list_does_not_mutate_input_order():
    jobs = [_job("a", 0.1), _job("b", 0.9)]
    original_order = list(jobs)
    fuse_by_rrf(jobs)
    assert jobs == original_order


class TestExtraRankField:
    def test_not_used_when_not_given(self):
        # A rerank_score present on the jobs shouldn't silently leak into the
        # ordering unless the caller explicitly opts in via extra_rank_field.
        jobs = [_job("a", embedding_score=0.9, rerank_score=0.1), _job("b", embedding_score=0.1, rerank_score=0.9)]
        result = fuse_by_rrf(jobs)
        assert [j["id"] for j in result] == ["a", "b"]

    def test_high_third_leg_score_moves_job_into_top_n_despite_mediocre_other_legs(self):
        # Regression: the exact audit scenario for the cross-encoder leg, a job
        # the Voyage reranker rated highly but with only mid-pack embedding and no
        # LLM score used to be entirely at the mercy of rerank_jobs' own cut,
        # since scripts/rank_jobs.py trusted the cross-encoder's order as final.
        fillers = [_job(f"filler{i}", embedding_score=0.9 - i * 0.01, rerank_score=None) for i in range(10)]
        target = _job("target", embedding_score=0.5, rerank_score=0.95)
        jobs = fillers + [target]

        by_embedding_only = sorted(jobs, key=lambda j: j["_embedding_score"], reverse=True)
        assert target not in by_embedding_only[:5]

        fused = fuse_by_rrf(jobs, extra_rank_field="rerank_score")
        assert fused[0]["id"] == "target"
        assert target in fused[:5]

    def test_missing_extra_field_contributes_nothing_rather_than_fabricated_rank(self):
        jobs = [_job("a", embedding_score=0.5, rerank_score=None), _job("b", embedding_score=0.4, rerank_score=0.9)]
        result = fuse_by_rrf(jobs, extra_rank_field="rerank_score")
        # "a" has no rerank_score at all (e.g. excluded by the caller as
        # unreliable), it should still rank purely on its embedding leg, not
        # crash or get treated as rerank_score=0.
        assert {j["id"] for j in result} == {"a", "b"}

    def test_all_three_legs_combine(self):
        # A job merely good across all three legs should be able to beat one
        # that's #1 on a single leg but weak elsewhere, the whole point of RRF
        # over picking a winner leg.
        balanced = _job("balanced", embedding_score=0.6, score=6.0, rerank_score=0.6)
        one_leg_winner = _job("winner_on_one_leg", embedding_score=0.99, score=None, rerank_score=0.1)
        others = [_job(f"filler{i}", embedding_score=0.3, score=3.0, rerank_score=0.3) for i in range(5)]
        jobs = [balanced, one_leg_winner] + others

        result = fuse_by_rrf(jobs, extra_rank_field="rerank_score")

        assert result.index(balanced) < result.index(one_leg_winner)
