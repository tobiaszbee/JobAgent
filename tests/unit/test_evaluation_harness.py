from db.repositories import job_repository
from evaluation.harness import divergence_cases, eval_report


def _insert_ranked(title, status, rank, url=None):
    job_id = job_repository.insert(
        title=title, company="Acme", location="Remote",
        url=url or f"https://example.com/{title.lower().replace(' ', '-')}-{rank}",
        source="linkedin",
    )
    job_repository.update_ranking_scores(job_id, embedding_score=0.9, rerank_score=0.8, listwise_rank=rank)
    if status != "new":
        job_repository.update_status(job_id, status)
    return job_id


class TestEvalReport:
    # precision@K and divergence-case CALCULATION are tested against JobAgentWeb's
    # own TestPrecisionAtK/TestDivergenceCases (tests/test_evaluation.py), the
    # canonical implementation now lives there, this just proxies it. These tests
    # only cover that the proxy round-trip and shape are correct.

    def test_report_structure(self):
        report = eval_report()
        assert "precision_at_10" in report
        assert "precision_at_5" in report
        assert "apply_rate_by_bucket" in report
        assert "divergence_cases" in report
        assert "total_ranked" in report
        assert "would_apply" in report
        assert "would_apply_score_floor" in report

    def test_report_combines_data(self):
        _insert_ranked("Applied top", "applied", 1)
        _insert_ranked("Rejected top", "rejected", 3)
        report = eval_report()
        assert report["n_evaluated_5"] == 2
        assert len(report["divergence_cases"]) == 1  # rank 3 + rejected → FP
        assert report["total_ranked"] == 2

    def test_apply_rate_by_bucket_grows_past_precision_at_ks_fixed_sample(self):
        # apply_rate_by_bucket's whole reason for existing: precision@5 is
        # permanently capped at 5 data points, the bucket for the same rank
        # range keeps growing with every decision in it.
        for i in range(7):
            _insert_ranked(f"Job {i}", "applied" if i % 2 == 0 else "rejected", 1, url=f"https://example.com/bucket-{i}")
        report = eval_report()
        assert report["n_evaluated_5"] == 5
        bucket = next(b for b in report["apply_rate_by_bucket"] if b["range"] == "1-5")
        assert bucket["n"] == 7

    def test_would_apply_reflects_repository_stats(self):
        job_id = job_repository.insert(
            title="Flagged job", company="Acme", location="Remote",
            url="https://ex.com/flagged", source="linkedin",
        )
        job_repository.update_would_apply(job_id, True, "Score 8.0 >= 7.0, no dealbreaker risk flagged")
        job_repository.update_status(job_id, "applied")
        report = eval_report()
        assert report["would_apply"]["flagged_total"] == 1
        assert report["would_apply"]["precision"] == 1.0

    def test_score_floor_reflects_local_config_not_jobagentweb_mirror(self, monkeypatch):
        # JobAgentWeb keeps its own copy of this value for its own display
        # convenience, JobAgent must never trust it over its own config, since
        # JobAgent is the one that actually enforces the floor.
        import evaluation.harness as harness
        monkeypatch.setitem(harness.WOULD_APPLY, "score_floor", 9.5)
        report = eval_report()
        assert report["would_apply_score_floor"] == 9.5


class TestDivergenceCases:
    def test_no_ranked_jobs_returns_empty(self):
        assert divergence_cases() == []

    def test_extracts_divergence_cases_from_the_report(self):
        _insert_ranked("Hidden gem", "applied", 18)
        cases = divergence_cases()
        assert len(cases) == 1
        assert cases[0]["divergence_type"] == "false_negative"
