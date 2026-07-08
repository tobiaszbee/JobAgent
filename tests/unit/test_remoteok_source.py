"""Unit tests for Remote OK source — no HTTP calls made."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from collector.sources.remoteok import RemoteOKSource
from collector.location import location_matches as _location_matches
from collector.utils import strip_html as _strip_html


# ── _location_matches ──────────────────────────────────────────────────────────


class TestLocationMatches:
    def test_remote_matches_all(self):
        assert _location_matches("USA Only", "Remote")

    def test_empty_location_matches_all(self):
        assert _location_matches("", "Poland")

    def test_worldwide_matches_any_country(self):
        assert _location_matches("Worldwide", "Germany")

    def test_anywhere_matches_any_country(self):
        assert _location_matches("Anywhere", "France")

    def test_europe_matches_eu_country(self):
        assert _location_matches("Europe", "Poland")

    def test_emea_matches_eu_country(self):
        assert _location_matches("EMEA", "Germany")

    def test_europe_does_not_match_us(self):
        assert not _location_matches("Europe Only", "United States")

    def test_usa_only_does_not_match_poland(self):
        assert not _location_matches("USA Only", "Poland")

    def test_direct_country_match(self):
        assert _location_matches("Poland, Ukraine", "Poland")

    def test_alias_uk(self):
        assert _location_matches("United Kingdom Only", "UK")

    def test_case_insensitive(self):
        assert _location_matches("POLAND", "poland")


# ── _strip_html ────────────────────────────────────────────────────────────────


class TestStripHtml:
    def test_strips_tags(self):
        assert _strip_html("<p>Hello</p>") == "Hello"

    def test_none_on_empty(self):
        assert _strip_html("") is None

    def test_br_to_newline(self):
        text = _strip_html("Line1<br>Line2")
        assert "Line1" in text and "Line2" in text


# ── RemoteOKSource.search() ───────────────────────────────────────────────────


def _make_job(
    slug: str = "php-dev-1",
    position: str = "Senior PHP Developer",
    company: str = "Acme",
    location: str = "Worldwide",
    days_ago: int = 0,
    tags: list[str] | None = None,
    description: str = "<p>Great role</p>",
) -> dict:
    pub = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return {
        "slug": slug,
        "url": f"https://remoteok.io/remote-jobs/{slug}",
        "position": position,
        "company": company,
        "location": location,
        "date": pub,
        "tags": tags if tags is not None else ["php", "backend"],
        "description": description,
    }


def _build_source(jobs: list[dict], days_back: int = 7) -> RemoteOKSource:
    src = RemoteOKSource(days_back=days_back)
    src._fetch_jobs = MagicMock(return_value=jobs)
    return src


class TestRemoteOKSourceSearch:
    def test_returns_matching_job(self):
        src = _build_source([_make_job()])
        results = src.search("PHP", "Remote")
        assert len(results) == 1
        assert results[0].title == "Senior PHP Developer"
        assert results[0].source == "remoteok"

    def test_source_id_is_slug(self):
        src = _build_source([_make_job(slug="php-dev-42")])
        results = src.search("PHP", "Remote")
        assert results[0].source_id == "php-dev-42"

    def test_url_preserved(self):
        src = _build_source([_make_job(slug="abc")])
        results = src.search("PHP", "Remote")
        assert results[0].url == "https://remoteok.io/remote-jobs/abc"

    def test_filters_by_date(self):
        fresh = _make_job(slug="new", days_ago=1)
        old   = _make_job(slug="old", days_ago=10)
        src = _build_source([fresh, old], days_back=7)
        results = src.search("PHP", "Remote")
        assert len(results) == 1
        assert results[0].source_id == "new"

    def test_filters_by_keyword_in_position(self):
        php = _make_job(slug="1", position="PHP Developer", tags=[])
        py  = _make_job(slug="2", position="Python Developer", tags=[])
        src = _build_source([php, py])
        results = src.search("PHP", "Remote")
        assert len(results) == 1
        assert results[0].source_id == "1"

    def test_does_not_match_keyword_only_in_tags(self):
        # RemoteOK tags are too noisy (generic categories applied to all jobs),
        # so only title is used for keyword filtering.
        job = _make_job(slug="1", position="Backend Developer", tags=["php", "laravel"])
        src = _build_source([job])
        results = src.search("PHP", "Remote")
        assert results == []

    def test_excludes_job_with_no_keyword_match(self):
        job = _make_job(slug="1", position="Python Developer", tags=["python", "django"])
        src = _build_source([job])
        results = src.search("PHP", "Remote")
        assert results == []

    def test_filters_by_location(self):
        eu  = _make_job(slug="1", location="Europe")
        us  = _make_job(slug="2", location="USA Only")
        src = _build_source([eu, us])
        results = src.search("PHP", "Poland")
        assert len(results) == 1
        assert results[0].source_id == "1"

    def test_empty_location_matches_all(self):
        job = _make_job(location="")
        src = _build_source([job])
        results = src.search("PHP", "Poland")
        assert len(results) == 1

    def test_skips_known_urls(self):
        job = _make_job(slug="php-1")
        src = _build_source([job])
        known = {"https://remoteok.io/remote-jobs/php-1"}
        results = src.search("PHP", "Remote", known_urls=known)
        assert results == []

    def test_respects_max_results(self):
        jobs = [_make_job(slug=f"job-{i}") for i in range(10)]
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
        src = _build_source([_make_job(company="GlobalTech")])
        results = src.search("PHP", "Remote")
        assert results[0].company == "GlobalTech"
