import uuid

from db.repositories import job_repository, dismissed_item_repository


def _insert_job(url="https://example.com/1", title="Backend Dev", company="AcmeCo"):
    # job_postings is shared/global and never truncated between tests — a fixed
    # literal url would collide with the same url from another test in this session.
    unique_url = f"{url}?t={uuid.uuid4().hex}"
    return job_repository.insert(
        title=title, company=company, location="UK (Remote)",
        url=unique_url, source="linkedin", description="PHP role.",
    )


class TestInsertAndGetForJob:
    def test_inserted_item_is_returned(self):
        job_id = _insert_job()
        dismissed_item_repository.insert(job_id, "con", "UK-based, timezone concern", "not an issue for me")
        items = dismissed_item_repository.get_for_job(job_id)
        assert len(items) == 1
        assert items[0]["item_type"] == "con"
        assert items[0]["item_text"] == "UK-based, timezone concern"
        assert items[0]["reason"] == "not an issue for me"

    def test_only_returns_items_for_that_job(self):
        job_a = _insert_job("https://example.com/a", title="Dev A", company="Corp A")
        job_b = _insert_job("https://example.com/b", title="Dev B", company="Corp B")
        dismissed_item_repository.insert(job_a, "con", "A concern", "reason a")
        dismissed_item_repository.insert(job_b, "con", "B concern", "reason b")
        assert len(dismissed_item_repository.get_for_job(job_a)) == 1
        assert dismissed_item_repository.get_for_job(job_a)[0]["item_text"] == "A concern"

    def test_no_items_returns_empty_list(self):
        job_id = _insert_job()
        assert dismissed_item_repository.get_for_job(job_id) == []

    def test_multiple_items_preserved_in_order(self):
        job_id = _insert_job()
        dismissed_item_repository.insert(job_id, "con", "First", "r1")
        dismissed_item_repository.insert(job_id, "pro", "Second", "r2")
        items = dismissed_item_repository.get_for_job(job_id)
        assert [i["item_text"] for i in items] == ["First", "Second"]


class TestGetRecentAndCount:
    def test_count_all_reflects_total_across_jobs(self):
        job_a = _insert_job("https://example.com/a", title="Dev A", company="Corp A")
        job_b = _insert_job("https://example.com/b", title="Dev B", company="Corp B")
        dismissed_item_repository.insert(job_a, "con", "A concern", "reason a")
        dismissed_item_repository.insert(job_b, "con", "B concern", "reason b")
        assert dismissed_item_repository.count_all() == 2

    def test_count_all_zero_when_none(self):
        assert dismissed_item_repository.count_all() == 0

    def test_get_recent_includes_job_title_and_company(self):
        job_id = _insert_job()
        dismissed_item_repository.insert(job_id, "con", "UK-based, timezone concern", "not an issue for me")
        recent = dismissed_item_repository.get_recent()
        assert len(recent) == 1
        assert recent[0]["title"] == "Backend Dev"
        assert recent[0]["company"] == "AcmeCo"

    def test_get_recent_respects_limit(self):
        job_id = _insert_job()
        for i in range(5):
            dismissed_item_repository.insert(job_id, "con", f"Concern {i}", "reason")
        assert len(dismissed_item_repository.get_recent(limit=3)) == 3

    def test_get_recent_most_recent_first(self):
        job_id = _insert_job()
        dismissed_item_repository.insert(job_id, "con", "Older", "r1")
        dismissed_item_repository.insert(job_id, "con", "Newer", "r2")
        recent = dismissed_item_repository.get_recent()
        assert recent[0]["item_text"] == "Newer"
