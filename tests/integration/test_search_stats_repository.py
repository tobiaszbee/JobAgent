from db.repositories import session_repository, search_stats_repository


class TestRecord:
    def test_record_is_queryable_via_summary(self):
        session_id = session_repository.start()
        search_stats_repository.record(session_id, "linkedin", "Senior PHP Developer", "Austria", cards_found=7, new_found=2)
        summary = search_stats_repository.get_query_summary("linkedin")
        assert len(summary) == 1
        assert summary[0]["search_query"] == "Senior PHP Developer"
        assert summary[0]["total_searches"] == 1
        assert summary[0]["total_new_found"] == 2

    def test_zero_cards_counted_as_zero_result_search(self):
        session_id = session_repository.start()
        search_stats_repository.record(session_id, "linkedin", "Full Stack Python Developer", "Austria", cards_found=0, new_found=0)
        summary = search_stats_repository.get_query_summary("linkedin")
        assert summary[0]["zero_result_searches"] == 1

    def test_nonzero_cards_not_counted_as_zero_result(self):
        session_id = session_repository.start()
        search_stats_repository.record(session_id, "linkedin", "PHP Developer", "Austria", cards_found=7, new_found=0)
        summary = search_stats_repository.get_query_summary("linkedin")
        assert summary[0]["zero_result_searches"] == 0


class TestGetQuerySummary:
    def test_aggregates_across_locations_and_sessions(self):
        session_id = session_repository.start()
        search_stats_repository.record(session_id, "linkedin", "PHP Developer", "Austria", cards_found=0, new_found=0)
        search_stats_repository.record(session_id, "linkedin", "PHP Developer", "Belgium", cards_found=0, new_found=0)
        session_id_2 = session_repository.start()
        search_stats_repository.record(session_id_2, "linkedin", "PHP Developer", "Austria", cards_found=5, new_found=1)

        summary = search_stats_repository.get_query_summary("linkedin")
        assert len(summary) == 1
        row = summary[0]
        assert row["total_searches"] == 3
        assert row["zero_result_searches"] == 2
        assert row["total_new_found"] == 1

    def test_filters_by_source(self):
        session_id = session_repository.start()
        search_stats_repository.record(session_id, "linkedin", "PHP Developer", "Austria", cards_found=0, new_found=0)
        search_stats_repository.record(session_id, "remotive", "PHP Developer", "Austria", cards_found=3, new_found=1)

        linkedin_summary = search_stats_repository.get_query_summary("linkedin")
        assert len(linkedin_summary) == 1
        assert linkedin_summary[0]["total_searches"] == 1

    def test_separate_rows_per_distinct_query(self):
        session_id = session_repository.start()
        search_stats_repository.record(session_id, "linkedin", "PHP Developer", "Austria", cards_found=5, new_found=1)
        search_stats_repository.record(session_id, "linkedin", "Python Developer", "Austria", cards_found=0, new_found=0)

        summary = search_stats_repository.get_query_summary("linkedin")
        assert {row["search_query"] for row in summary} == {"PHP Developer", "Python Developer"}

    def test_returns_empty_when_no_stats_recorded(self):
        assert search_stats_repository.get_query_summary("linkedin") == []
