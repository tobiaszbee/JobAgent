from db.repositories import job_repository


def _insert(url="https://example.com/job/1", **kwargs):
    defaults = dict(title="PHP Developer", company="Acme Corp",
                    location="Poland", source="linkedin",
                    description="Symfony experience required.")
    return job_repository.insert(**{**defaults, "url": url, **kwargs})


class TestInsert:
    def test_returns_16_char_id_on_success(self):
        job_id = _insert()
        assert job_id is not None
        assert len(job_id) == 16

    def test_duplicate_url_returns_none(self):
        _insert()
        assert _insert() is None

    def test_same_title_same_company_different_url_returns_none(self):
        _insert(url="https://a.com/1")
        assert _insert(url="https://a.com/2") is None

    def test_same_title_different_company_is_allowed(self):
        _insert(company="Acme", url="https://a.com/1")
        job_id = _insert(company="Beta Corp", url="https://a.com/2")
        assert job_id is not None

    def test_insert_without_description_succeeds(self):
        job_id = job_repository.insert(
            "PHP Dev", "Co", "PL", "https://a.com/nodesc", "linkedin"
        )
        assert job_id is not None


class TestGetUnscored:
    def test_returns_job_with_description(self):
        _insert()
        assert len(job_repository.get_unscored()) == 1

    def test_excludes_job_without_description(self):
        job_repository.insert("No desc", "Co", "PL", "https://a.com/nd", "linkedin")
        assert job_repository.get_unscored() == []

    def test_excludes_job_with_empty_description(self):
        job_id = _insert()
        job_repository.update_description(job_id, "")
        assert job_repository.get_unscored() == []

    def test_excludes_already_scored_job(self):
        job_id = _insert()
        job_repository.update_score(job_id, 7.5, "Good match")
        assert job_repository.get_unscored() == []

    def test_excludes_auto_rejected_job(self):
        job_id = _insert()
        job_repository.update_score_and_status(job_id, 0.0, "On-site only", "auto_rejected")
        assert job_repository.get_unscored() == []


class TestUpdateScoreAndStatus:
    def test_both_fields_updated_atomically(self):
        job_id = _insert()
        job_repository.update_score_and_status(job_id, 0.0, "Rejected", "auto_rejected")
        stats = job_repository.get_stats()
        assert stats["auto_rejected"] == 1
        assert stats["new"] == 0

    def test_auto_rejected_no_longer_appears_in_unscored(self):
        job_id = _insert()
        job_repository.update_score_and_status(job_id, 0.0, "Rejected", "auto_rejected")
        assert job_repository.get_unscored() == []


class TestGetExamples:
    def test_applied_job_in_positive_list(self):
        job_id = _insert()
        job_repository.update_status(job_id, "applied")
        pos, neg = job_repository.get_examples()
        assert len(pos) == 1 and pos[0]["id"] == job_id

    def test_rejected_job_in_negative_list(self):
        job_id = _insert()
        job_repository.update_status(job_id, "rejected")
        pos, neg = job_repository.get_examples()
        assert len(neg) == 1 and neg[0]["id"] == job_id

    def test_auto_rejected_excluded_from_both_lists(self):
        job_id = _insert()
        job_repository.update_score_and_status(job_id, 0.0, "Bad", "auto_rejected")
        pos, neg = job_repository.get_examples()
        assert pos == [] and neg == []

    def test_new_job_excluded_from_both_lists(self):
        _insert()
        pos, neg = job_repository.get_examples()
        assert pos == [] and neg == []


class TestSearch:
    def test_no_filters_returns_all(self):
        _insert(url="https://a.com/1")
        _insert(company="Beta", url="https://a.com/2")
        assert len(job_repository.search()) == 2

    def test_filter_by_status(self):
        id1 = _insert(url="https://a.com/1")
        _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "reviewed")
        result = job_repository.search(status="reviewed")
        assert len(result) == 1 and result[0]["id"] == id1

    def test_filter_by_min_score_excludes_lower_scored_jobs(self):
        id1 = _insert(url="https://a.com/1")
        id2 = _insert(company="Beta", url="https://a.com/2")
        job_repository.update_score(id1, 8.0, "Great")
        job_repository.update_score(id2, 3.0, "Weak")
        result = job_repository.search(min_score=6.0)
        ids = [r["id"] for r in result]
        assert id1 in ids
        assert id2 not in ids

    def test_filter_by_text_query_matches_title(self):
        _insert(title="PHP Developer", url="https://a.com/1")
        _insert(title="Java Engineer", company="Beta", url="https://a.com/2")
        result = job_repository.search(query="PHP")
        assert len(result) == 1 and result[0]["title"] == "PHP Developer"


class TestGetMissingDescriptions:
    def test_returns_job_without_description(self):
        job_repository.insert("Dev", "Co", "PL", "https://a.com/nd", "linkedin")
        result = job_repository.get_missing_descriptions()
        assert len(result) == 1
        assert "id" in result[0] and "url" in result[0]

    def test_excludes_job_with_description(self):
        _insert()  # has description in defaults
        assert job_repository.get_missing_descriptions() == []

    def test_excludes_already_scored_job(self):
        job_id = job_repository.insert("Dev", "Co", "PL", "https://a.com/s", "linkedin")
        job_repository.update_score(job_id, 7.0, "OK")
        assert job_repository.get_missing_descriptions() == []


class TestGetStats:
    def test_empty_db_returns_zeros(self):
        stats = job_repository.get_stats()
        assert stats["total"] == 0
        assert stats["new"] == 0

    def test_includes_last_run_key(self):
        stats = job_repository.get_stats()
        assert "last_run" in stats

    def test_last_run_is_none_when_no_sessions(self):
        stats = job_repository.get_stats()
        assert stats["last_run"] is None

    def test_counts_per_status(self):
        id1 = _insert(url="https://a.com/1")
        id2 = _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "applied")
        job_repository.update_score_and_status(id2, 0.0, "Bad", "auto_rejected")
        stats = job_repository.get_stats()
        assert stats["total"] == 2
        assert stats["applied"] == 1
        assert stats["auto_rejected"] == 1
        assert stats["new"] == 0


class TestGetAllUrls:
    def test_returns_empty_set_when_no_jobs(self):
        assert job_repository.get_all_urls() == set()

    def test_returns_all_inserted_urls(self):
        _insert(url="https://a.com/1")
        _insert(company="Beta", url="https://a.com/2")
        urls = job_repository.get_all_urls()
        assert urls == {"https://a.com/1", "https://a.com/2"}


class TestGetNew:
    def test_returns_new_jobs_only(self):
        id1 = _insert(url="https://a.com/1")
        id2 = _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id2, "applied")
        result = job_repository.get_new()
        assert len(result) == 1 and result[0]["id"] == id1


class TestGetNewWithDescriptions:
    def test_returns_new_jobs_with_descriptions(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.insert("No desc", "Co", "PL", "https://a.com/nd", "linkedin")
        result = job_repository.get_new_with_descriptions()
        ids = [r["id"] for r in result]
        assert id1 in ids

    def test_excludes_jobs_without_description(self):
        job_repository.insert("No desc", "Co", "PL", "https://a.com/nd", "linkedin")
        result = job_repository.get_new_with_descriptions()
        assert result == []


class TestGetByStatus:
    def test_returns_only_matching_status(self):
        id1 = _insert(url="https://a.com/1")
        _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "applied")
        result = job_repository.get_by_status("applied")
        assert len(result) == 1 and result[0]["id"] == id1


class TestGetAllFeedback:
    def test_applied_jobs_in_first_list(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_status(id1, "applied")
        applied, rejected = job_repository.get_all_feedback()
        assert len(applied) == 1

    def test_rejected_jobs_in_second_list(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_status(id1, "rejected")
        applied, rejected = job_repository.get_all_feedback()
        assert len(rejected) == 1

    def test_new_jobs_excluded(self):
        _insert(url="https://a.com/1")
        applied, rejected = job_repository.get_all_feedback()
        assert applied == [] and rejected == []


class TestGetFeedbackSince:
    def test_returns_decisions_after_timestamp(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_status(id1, "applied")
        applied, rejected = job_repository.get_feedback_since("2000-01-01")
        assert len(applied) == 1

    def test_excludes_decisions_before_timestamp(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_status(id1, "applied")
        applied, rejected = job_repository.get_feedback_since("2099-01-01")
        assert applied == []


class TestCountByFilter:
    def test_returns_zero_for_empty_statuses(self):
        assert job_repository.count_by_filter([]) == 0

    def test_counts_matching_status(self):
        id1 = _insert(url="https://a.com/1")
        _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "applied")
        assert job_repository.count_by_filter(["applied"]) == 1

    def test_counts_multiple_statuses(self):
        id1 = _insert(url="https://a.com/1")
        id2 = _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "applied")
        job_repository.update_status(id2, "rejected")
        assert job_repository.count_by_filter(["applied", "rejected"]) == 2


class TestDeleteByFilter:
    def test_deletes_matching_jobs_and_returns_count(self):
        id1 = _insert(url="https://a.com/1")
        _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "rejected")
        deleted = job_repository.delete_by_filter(["rejected"])
        assert deleted == 1
        assert job_repository.count_by_filter(["rejected"]) == 0

    def test_returns_zero_for_empty_statuses(self):
        assert job_repository.delete_by_filter([]) == 0


class TestUpdateStructuredData:
    def test_stores_and_retrieves_json(self):
        import json
        id1 = _insert(url="https://a.com/1")
        data = {"remote": True, "seniority": "senior", "stack": ["python"]}
        job_repository.update_structured_data(id1, data)
        result = job_repository.search()
        stored = json.loads(result[0]["structured_data"])
        assert stored["seniority"] == "senior"
        assert stored["stack"] == ["python"]


class TestUpdateRankingScores:
    def test_updates_all_ranking_fields(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_ranking_scores(id1, embedding_score=0.88, rerank_score=0.75, listwise_rank=3)
        result = job_repository.search()
        job = result[0]
        assert abs(job["embedding_score"] - 0.88) < 1e-9
        assert abs(job["rerank_score"] - 0.75) < 1e-9
        assert job["listwise_rank"] == 3

    def test_accepts_none_values(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_ranking_scores(id1, None, None, None)  # should not raise


class TestGetJobsForRanking:
    def test_returns_new_jobs_without_listwise_rank(self):
        id1 = _insert(url="https://a.com/1")
        result = job_repository.get_jobs_for_ranking()
        ids = [r["id"] for r in result]
        assert id1 in ids

    def test_excludes_already_ranked_jobs(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_ranking_scores(id1, None, None, listwise_rank=1)
        result = job_repository.get_jobs_for_ranking()
        assert result == []

    def test_excludes_jobs_without_descriptions(self):
        job_repository.insert("No desc", "Co", "PL", "https://a.com/nd", "linkedin")
        assert job_repository.get_jobs_for_ranking() == []


class TestGetAppliedAndRejectedJobIds:
    def test_get_applied_job_ids(self):
        id1 = _insert(url="https://a.com/1")
        id2 = _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "applied")
        result = job_repository.get_applied_job_ids()
        assert id1 in result
        assert id2 not in result

    def test_get_rejected_job_ids(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_status(id1, "rejected")
        assert id1 in job_repository.get_rejected_job_ids()

    def test_empty_when_no_matching_jobs(self):
        _insert(url="https://a.com/1")  # status=new
        assert job_repository.get_applied_job_ids() == []
        assert job_repository.get_rejected_job_ids() == []


class TestCountDecisions:
    def test_zero_when_no_decisions(self):
        _insert(url="https://a.com/1")  # status=new
        assert job_repository.count_decisions() == 0

    def test_counts_applied_and_rejected(self):
        id1 = _insert(url="https://a.com/1")
        id2 = _insert(company="Beta", url="https://a.com/2")
        job_repository.update_status(id1, "applied")
        job_repository.update_status(id2, "rejected")
        assert job_repository.count_decisions() == 2


class TestUpdateStatusWithRejectionReason:
    def test_stores_rejection_reason(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_status(id1, "rejected", rejection_reason="stawka za niska")
        result = job_repository.search(status="rejected")
        assert result[0]["rejection_reason"] == "stawka za niska"

    def test_no_rejection_reason_for_other_statuses(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_status(id1, "applied", rejection_reason="ignored")
        result = job_repository.search(status="applied")
        assert result[0]["rejection_reason"] is None


class TestGetStatsRanked:
    def test_ranked_count_in_stats(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_ranking_scores(id1, None, None, listwise_rank=1)
        stats = job_repository.get_stats()
        assert stats["ranked"] == 1

    def test_ranked_excludes_non_new_status(self):
        id1 = _insert(url="https://a.com/1")
        job_repository.update_ranking_scores(id1, None, None, listwise_rank=1)
        job_repository.update_status(id1, "applied")
        stats = job_repository.get_stats()
        assert stats["ranked"] == 0
