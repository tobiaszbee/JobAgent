"""Unit tests for Working Nomads source — no HTTP calls made."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from collector.sources.workingnomads import WorkingNomadsSource, _canonical_url
from collector.utils import strip_html as _strip_html


# ── _canonical_url ─────────────────────────────────────────────────────────────


class TestCanonicalUrl:
    def test_absolute_url_unchanged(self):
        assert _canonical_url("https://example.com/job/1") == "https://example.com/job/1"

    def test_relative_with_slash_prepends_base(self):
        assert _canonical_url("/jobs/php-dev") == "https://www.workingnomads.com/jobs/php-dev"

    def test_relative_without_slash_prepends_base_and_slash(self):
        assert _canonical_url("jobs/php-dev") == "https://www.workingnomads.com/jobs/php-dev"


# ── _strip_html ────────────────────────────────────────────────────────────────


class TestStripHtml:
    def test_strips_tags(self):
        assert _strip_html("<p>Hello</p>") == "Hello"

    def test_none_on_empty(self):
        assert _strip_html("") is None

    def test_br_becomes_whitespace(self):
        text = _strip_html("Line1<br>Line2")
        assert "Line1" in text and "Line2" in text


# ── WorkingNomadsSource.search() ──────────────────────────────────────────────


def _make_job(
    job_id: int = 1,
    title: str = "Senior PHP Developer",
    company_name: str = "Acme",
    location: str = "Remote",
    days_ago: int = 0,
    tags: list[dict] | None = None,
    description: str = "<p>Great role</p>",
    url: str | None = None,
) -> dict:
    pub = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return {
        "id": job_id,
        "url": url or f"https://www.workingnomads.com/jobs/php-{job_id}",
        "title": title,
        "company_name": company_name,
        "location": location,
        "pub_date": pub,
        "tags": tags if tags is not None else [{"name": "php"}, {"name": "backend"}],
        "description": description,
    }


def _build_source(jobs: list[dict], days_back: int = 7) -> WorkingNomadsSource:
    src = WorkingNomadsSource(days_back=days_back)
    src._fetch_jobs = MagicMock(return_value=jobs)
    return src


class TestWorkingNomadsSearch:
    def test_returns_matching_job(self):
        src = _build_source([_make_job()])
        results = src.search("PHP", "Remote")
        assert len(results) == 1
        assert results[0].title == "Senior PHP Developer"
        assert results[0].source == "workingnomads"

    def test_source_id_is_job_id(self):
        src = _build_source([_make_job(job_id=42)])
        results = src.search("PHP", "Remote")
        assert results[0].source_id == "42"

    def test_url_preserved(self):
        src = _build_source([_make_job(job_id=7)])
        results = src.search("PHP", "Remote")
        assert results[0].url == "https://www.workingnomads.com/jobs/php-7"

    def test_relative_url_canonicalized(self):
        job = _make_job(url="/jobs/php-dev-1")
        src = _build_source([job])
        results = src.search("PHP", "Remote")
        assert results[0].url == "https://www.workingnomads.com/jobs/php-dev-1"

    def test_filters_by_date(self):
        fresh = _make_job(job_id=1, days_ago=1)
        old   = _make_job(job_id=2, days_ago=10)
        src = _build_source([fresh, old], days_back=7)
        results = src.search("PHP", "Remote")
        assert len(results) == 1
        assert results[0].source_id == "1"

    def test_filters_by_keyword_in_title(self):
        php = _make_job(job_id=1, title="PHP Developer", tags=[])
        py  = _make_job(job_id=2, title="Python Developer", tags=[])
        src = _build_source([php, py])
        results = src.search("PHP", "Remote")
        assert len(results) == 1
        assert results[0].source_id == "1"

    def test_matches_keyword_in_tags(self):
        job = _make_job(title="Backend Developer", tags=[{"name": "php"}, {"name": "laravel"}])
        src = _build_source([job])
        results = src.search("PHP", "Remote")
        assert len(results) == 1

    def test_excludes_job_with_no_keyword_match(self):
        job = _make_job(job_id=1, title="Python Developer", tags=[{"name": "python"}])
        src = _build_source([job])
        results = src.search("PHP", "Remote")
        assert results == []

    def test_skips_known_urls(self):
        job = _make_job(job_id=5)
        src = _build_source([job])
        known = {"https://www.workingnomads.com/jobs/php-5"}
        results = src.search("PHP", "Remote", known_urls=known)
        assert results == []

    def test_known_url_check_uses_canonical(self):
        job = _make_job(url="/jobs/php-dev")
        src = _build_source([job])
        known = {"https://www.workingnomads.com/jobs/php-dev"}
        results = src.search("PHP", "Remote", known_urls=known)
        assert results == []

    def test_respects_max_results(self):
        jobs = [_make_job(job_id=i) for i in range(10)]
        src = _build_source(jobs)
        results = src.search("PHP", "Remote", max_results=3)
        assert len(results) == 3

    def test_description_stripped(self):
        src = _build_source([_make_job(description="<p>Good <b>role</b></p>")])
        results = src.search("PHP", "Remote")
        assert results[0].description == "Good role"

    def test_empty_response_returns_empty(self):
        src = _build_source([])
        results = src.search("PHP", "Remote")
        assert results == []

    def test_skips_job_without_url(self):
        job = _make_job()
        job["url"] = ""
        src = _build_source([job])
        results = src.search("PHP", "Remote")
        assert results == []

    def test_location_fallback_to_remote(self):
        job = _make_job(location="")
        src = _build_source([job])
        results = src.search("PHP", "Remote")
        assert results[0].location == "Remote"

    def test_company_extracted(self):
        src = _build_source([_make_job(company_name="GlobalTech")])
        results = src.search("PHP", "Remote")
        assert results[0].company == "GlobalTech"

    def test_location_worldwide_matches_any_country(self):
        src = _build_source([_make_job(location="Worldwide")])
        results = src.search("PHP", "Poland")
        assert len(results) == 1

    def test_location_europe_matches_poland(self):
        src = _build_source([_make_job(location="Europe only")])
        results = src.search("PHP", "Poland")
        assert len(results) == 1

    def test_location_usa_only_excluded_for_poland(self):
        src = _build_source([_make_job(location="USA only")])
        results = src.search("PHP", "Poland")
        assert results == []

    def test_location_remote_search_matches_all(self):
        usa = _make_job(job_id=1, location="USA only")
        eu  = _make_job(job_id=2, location="Europe only")
        src = _build_source([usa, eu])
        results = src.search("PHP", "Remote")
        assert len(results) == 2
