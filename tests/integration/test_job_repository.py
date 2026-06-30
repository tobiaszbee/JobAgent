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


class TestGetStats:
    def test_empty_db_returns_zeros(self):
        stats = job_repository.get_stats()
        assert stats["total"] == 0
        assert stats["new"] == 0

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
