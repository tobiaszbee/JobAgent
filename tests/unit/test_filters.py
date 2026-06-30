from collector.base import RawJob
from collector.filters import apply_filters


def _job(title="Dev", company="Acme", location="Poland", url=None):
    return RawJob(
        title=title,
        company=company,
        location=location,
        url=url or f"https://example.com/{title.lower().replace(' ', '-')}",
        source="linkedin",
    )


class TestApplyFilters:
    def test_empty_keywords_returns_same_list(self):
        jobs = [_job("PHP Dev"), _job("Java Dev")]
        assert apply_filters(jobs, []) is jobs

    def test_filters_by_title(self):
        jobs = [_job("PHP Developer"), _job("Java Developer")]
        result = apply_filters(jobs, ["Java"])
        assert len(result) == 1
        assert result[0].title == "PHP Developer"

    def test_filter_is_case_insensitive(self):
        jobs = [_job("JAVA ENGINEER"), _job("PHP Developer")]
        result = apply_filters(jobs, ["java"])
        assert len(result) == 1
        assert result[0].title == "PHP Developer"

    def test_filters_by_company(self):
        jobs = [_job(company="Evil Corp", url="https://a.com/1"),
                _job(company="Good Inc", url="https://a.com/2")]
        result = apply_filters(jobs, ["Evil"])
        assert len(result) == 1
        assert result[0].company == "Good Inc"

    def test_filters_by_location(self):
        jobs = [_job(location="UK Only", url="https://a.com/1"),
                _job(location="Poland", url="https://a.com/2")]
        result = apply_filters(jobs, ["UK"])
        assert len(result) == 1
        assert result[0].location == "Poland"

    def test_empty_jobs_list(self):
        assert apply_filters([], ["PHP"]) == []

    def test_all_filtered_returns_empty_list(self):
        jobs = [_job("Java Dev"), _job("Java Engineer", url="https://a.com/2")]
        assert apply_filters(jobs, ["Java"]) == []

    def test_multiple_keywords_any_match_filters(self):
        jobs = [_job("Java Dev"), _job("PHP Dev", url="https://a.com/2"),
                _job("Python Dev", url="https://a.com/3")]
        result = apply_filters(jobs, ["Java", "Python"])
        assert len(result) == 1
        assert result[0].title == "PHP Dev"

    def test_partial_word_match(self):
        jobs = [_job("PHP/JavaScript Developer"), _job("PHP Developer", url="https://a.com/2")]
        result = apply_filters(jobs, ["javascript"])
        assert len(result) == 1
        assert result[0].title == "PHP Developer"
