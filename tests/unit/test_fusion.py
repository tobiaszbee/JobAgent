from ranker.fusion import fuse_by_rrf


def _job(id_, embedding_score=None, score=None):
    return {"id": id_, "_embedding_score": embedding_score, "score": score}


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
    # Regression: this is the exact audit scenario — a job the LLM scorer rated
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


def test_returns_new_list_does_not_mutate_input_order():
    jobs = [_job("a", 0.1), _job("b", 0.9)]
    original_order = list(jobs)
    fuse_by_rrf(jobs)
    assert jobs == original_order
