from db.repositories import job_repository
from evaluation.harness import precision_at_k, divergence_cases, eval_report


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


class TestPrecisionAtK:
    def test_no_ranked_jobs_returns_none(self):
        result = precision_at_k(10)
        assert result["precision_at_k"] is None
        assert result["n_evaluated"] == 0

    def test_all_applied_is_perfect_precision(self):
        for i in range(5):
            _insert_ranked(f"Job {i}", "applied", i + 1, url=f"https://ex.com/{i}")
        result = precision_at_k(5)
        assert result["precision_at_k"] == 1.0
        assert result["n_positive"] == 5

    def test_all_rejected_is_zero_precision(self):
        for i in range(5):
            _insert_ranked(f"Job {i}", "rejected", i + 1, url=f"https://ex.com/{i}")
        result = precision_at_k(5)
        assert result["precision_at_k"] == 0.0

    def test_mixed_precision(self):
        _insert_ranked("Applied job", "applied", 1)
        _insert_ranked("Rejected job", "rejected", 2)
        result = precision_at_k(2)
        assert result["precision_at_k"] == 0.5

    def test_k_limits_results(self):
        for i in range(10):
            _insert_ranked(f"Job {i}", "applied" if i < 5 else "rejected", i + 1, url=f"https://ex.com/{i}")
        result = precision_at_k(3)
        assert result["n_evaluated"] == 3
        assert result["precision_at_k"] == 1.0

    def test_unranked_jobs_excluded(self):
        job_id = job_repository.insert(
            title="Unranked", company="Co", location="Remote",
            url="https://ex.com/unranked", source="linkedin",
        )
        job_repository.update_status(job_id, "applied")
        result = precision_at_k(10)
        assert result["n_evaluated"] == 0

    def test_reviewed_counts_as_positive(self):
        _insert_ranked("Reviewed job", "reviewed", 1)
        result = precision_at_k(1)
        assert result["n_positive"] == 1


class TestDivergenceCases:
    def test_no_ranked_jobs_returns_empty(self):
        assert divergence_cases() == []

    def test_false_positive_high_rank_rejected(self):
        _insert_ranked("Great-looking job", "rejected", 2)
        cases = divergence_cases()
        assert len(cases) == 1
        assert cases[0]["divergence_type"] == "false_positive"

    def test_false_negative_low_rank_applied(self):
        _insert_ranked("Hidden gem", "applied", 18)
        cases = divergence_cases()
        assert len(cases) == 1
        assert cases[0]["divergence_type"] == "false_negative"

    def test_middle_rank_not_flagged(self):
        _insert_ranked("Normal job", "rejected", 10)
        assert divergence_cases() == []

    def test_applied_high_rank_not_flagged(self):
        _insert_ranked("Expected pick", "applied", 3)
        assert divergence_cases() == []

    def test_rejected_low_rank_not_flagged(self):
        _insert_ranked("Expected miss", "rejected", 17)
        assert divergence_cases() == []

    def test_boundary_rank_5_rejected_is_false_positive(self):
        _insert_ranked("Boundary FP", "rejected", 5)
        cases = divergence_cases()
        assert any(c["divergence_type"] == "false_positive" for c in cases)

    def test_boundary_rank_16_applied_is_false_negative(self):
        _insert_ranked("Boundary FN", "applied", 16)
        cases = divergence_cases()
        assert any(c["divergence_type"] == "false_negative" for c in cases)


class TestEvalReport:
    def test_report_structure(self):
        report = eval_report()
        assert "precision_at_10" in report
        assert "precision_at_5" in report
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
