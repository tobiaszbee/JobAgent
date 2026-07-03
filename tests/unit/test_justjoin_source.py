"""Unit tests for the JustJoin.it scraper — no HTTP calls made."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from collector.sources.justjoin import (
    JustJoinSource,
    _extract_ld_json,
    _match_location,
    _strip_html,
    _tech_slug,
)


# ── _tech_slug ─────────────────────────────────────────────────────────────────


class TestTechSlug:
    def test_php(self):
        assert _tech_slug("PHP Developer") == "php"

    def test_python(self):
        assert _tech_slug("Senior Python Engineer") == "python"

    def test_javascript_via_react(self):
        assert _tech_slug("React Frontend Developer") == "javascript"

    def test_typescript(self):
        assert _tech_slug("TypeScript Developer") == "javascript"

    def test_csharp(self):
        assert _tech_slug("C# .NET Developer") == "net"

    def test_golang(self):
        assert _tech_slug("Golang Backend") == "go"

    def test_case_insensitive(self):
        assert _tech_slug("php developer") == "php"

    def test_fallback_to_all_locations(self):
        assert _tech_slug("Software Engineer") == "all-locations"

    def test_devops(self):
        assert _tech_slug("DevOps Engineer") == "devops"


# ── _match_location ────────────────────────────────────────────────────────────


class TestMatchLocation:
    def test_poland_matches_when_city_present(self):
        assert _match_location("Warsaw", "Poland", False, "Poland")

    def test_poland_matches_by_country_name(self):
        assert _match_location("Wrocław", "Poland", False, "Poland")

    def test_poland_no_match_wrong_country_and_empty_city(self):
        assert not _match_location("", "Germany", False, "Poland")

    def test_city_substring_match(self):
        assert _match_location("Warsaw", "Poland", False, "Warsaw")

    def test_city_case_insensitive(self):
        assert _match_location("Warsaw", "Poland", False, "warsaw")

    def test_city_no_match_different_city(self):
        assert not _match_location("Kraków", "Poland", False, "Warsaw")

    def test_remote_matches_when_remote_flag_set(self):
        assert _match_location("Warsaw", "Poland", True, "Remote")

    def test_remote_no_match_for_non_remote_offer(self):
        assert not _match_location("Warsaw", "Poland", False, "Remote")

    def test_zdalne_matches_remote_flag(self):
        assert _match_location("", "Poland", True, "zdalne")

    def test_city_in_country_bucket(self):
        assert _match_location("Kraków", "Poland", False, "Kraków")


# ── _strip_html ────────────────────────────────────────────────────────────────


class TestStripHtml:
    def test_strips_tags(self):
        assert _strip_html("<p>Hello world</p>") == "Hello world"

    def test_newlines_on_block_elements(self):
        text = _strip_html("<p>Line one</p><p>Line two</p>")
        assert "Line one" in text
        assert "Line two" in text

    def test_li_items(self):
        text = _strip_html("<ul><li>Item A</li><li>Item B</li></ul>")
        assert "Item A" in text
        assert "Item B" in text

    def test_nested_tags(self):
        assert _strip_html("<div><strong>Bold</strong> text</div>") == "Bold text"

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_plain_text_unchanged(self):
        assert _strip_html("no tags here") == "no tags here"


# ── _extract_ld_json ───────────────────────────────────────────────────────────


def _ld_script(data: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


class TestExtractLdJson:
    def test_finds_matching_type(self):
        html = _ld_script({"@type": "JobPosting", "title": "Dev"})
        d = _extract_ld_json(html, "JobPosting")
        assert d is not None
        assert d["title"] == "Dev"

    def test_returns_none_for_wrong_type(self):
        html = _ld_script({"@type": "CollectionPage"})
        assert _extract_ld_json(html, "JobPosting") is None

    def test_finds_second_script_of_matching_type(self):
        html = (
            _ld_script({"@type": "WebPage"})
            + _ld_script({"@type": "JobPosting", "title": "Dev"})
        )
        d = _extract_ld_json(html, "JobPosting")
        assert d is not None

    def test_returns_none_on_invalid_json(self):
        html = '<script type="application/ld+json">{broken json}</script>'
        assert _extract_ld_json(html, "JobPosting") is None

    def test_returns_none_when_no_script_present(self):
        assert _extract_ld_json("<html><body></body></html>", "JobPosting") is None


# ── JustJoinSource.search() ────────────────────────────────────────────────────


def _make_posting(
    slug: str = "acme-php-dev-warsaw",
    title: str = "PHP Developer",
    company: str = "Acme",
    city: str = "Warsaw",
    country: str = "Poland",
    is_remote: bool = False,
    days_ago: int = 0,
    description_html: str = "<p>Great job</p>",
) -> tuple[str, dict]:
    date_str = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    posting: dict = {
        "@type": "JobPosting",
        "title": title,
        "datePosted": date_str,
        "description": description_html,
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": city,
                "addressCountry": "PL",
            },
        },
        "applicantLocationRequirements": {"@type": "Country", "name": country},
    }
    if is_remote:
        posting["jobLocationType"] = "TELECOMMUTE"
    return slug, posting


def _build_source(slugs_and_postings: list[tuple[str, dict]], days_back: int = 7) -> JustJoinSource:
    """Return a JustJoinSource with HTTP methods replaced by MagicMocks."""
    src = JustJoinSource(days_back=days_back)
    src._client = MagicMock()
    postings = {
        f"https://justjoin.it/job-offer/{slug}": p
        for slug, p in slugs_and_postings
    }
    src._get_listing_urls = MagicMock(return_value=list(postings.keys()))
    src._get_job_posting = MagicMock(side_effect=lambda u: postings.get(u))
    return src


class TestJustJoinSourceSearch:
    def test_returns_matching_offer(self):
        src = _build_source([_make_posting()])
        results = src.search("PHP Developer", "Poland")
        assert len(results) == 1
        assert results[0].title == "PHP Developer"
        assert results[0].source == "justjoin"

    def test_source_id_is_slug(self):
        src = _build_source([_make_posting(slug="my-company-dev-warsaw")])
        results = src.search("PHP Developer", "Poland")
        assert results[0].source_id == "my-company-dev-warsaw"

    def test_url_contains_job_offer_path(self):
        src = _build_source([_make_posting(slug="acme-php-dev-warsaw")])
        results = src.search("PHP Developer", "Poland")
        assert results[0].url == "https://justjoin.it/job-offer/acme-php-dev-warsaw"

    def test_filters_by_location(self):
        pl = _make_posting(slug="pl-job", city="Warsaw", country="Poland")
        de = _make_posting(slug="de-job", city="Berlin", country="Germany")
        src = _build_source([pl, de])
        results = src.search("PHP Developer", "Poland")
        assert len(results) == 1
        assert results[0].source_id == "pl-job"

    def test_filters_by_days_back(self):
        recent = _make_posting(slug="recent", days_ago=1)
        old = _make_posting(slug="old", days_ago=10)
        src = _build_source([recent, old], days_back=7)
        results = src.search("PHP Developer", "Poland")
        assert len(results) == 1
        assert results[0].source_id == "recent"

    def test_skips_known_urls(self):
        src = _build_source([_make_posting(slug="acme-php-dev-warsaw")])
        known = {"https://justjoin.it/job-offer/acme-php-dev-warsaw"}
        results = src.search("PHP Developer", "Poland", known_urls=known)
        assert results == []

    def test_respects_max_results(self):
        postings = [_make_posting(slug=f"job-{i}") for i in range(10)]
        src = _build_source(postings)
        results = src.search("PHP Developer", "Poland", max_results=3)
        assert len(results) == 3

    def test_description_stripped_from_html(self):
        src = _build_source([_make_posting(description_html="<p>Great job</p>")])
        results = src.search("PHP Developer", "Poland")
        assert results[0].description == "Great job"

    def test_description_none_when_html_empty(self):
        src = _build_source([_make_posting(description_html="")])
        results = src.search("PHP Developer", "Poland")
        assert results[0].description is None

    def test_remote_offer_matches_remote_location(self):
        src = _build_source([_make_posting(city="Warsaw", is_remote=True)])
        results = src.search("PHP Developer", "Remote")
        assert len(results) == 1

    def test_non_remote_offer_does_not_match_remote_location(self):
        src = _build_source([_make_posting(city="Warsaw", is_remote=False)])
        results = src.search("PHP Developer", "Remote")
        assert results == []

    def test_remote_location_string_city_slash_remote(self):
        src = _build_source([_make_posting(city="Kraków", is_remote=True)])
        results = src.search("PHP Developer", "Remote")
        assert results[0].location == "Kraków / Remote"

    def test_remote_only_no_city(self):
        src = _build_source([_make_posting(city="", is_remote=True)])
        results = src.search("PHP Developer", "Remote")
        assert results[0].location == "Remote"

    def test_company_extracted_from_hiring_org(self):
        src = _build_source([_make_posting(company="SuperCorp")])
        results = src.search("PHP Developer", "Poland")
        assert results[0].company == "SuperCorp"

    def test_uses_php_tech_slug_for_php_query(self):
        src = _build_source([_make_posting()])
        src.search("PHP Developer", "Poland")
        src._get_listing_urls.assert_called_once_with("php")

    def test_uses_all_locations_slug_for_generic_query(self):
        src = _build_source([_make_posting()])
        src.search("Software Engineer", "Poland")
        src._get_listing_urls.assert_called_once_with("all-locations")

    def test_empty_listing_returns_empty(self):
        src = _build_source([])
        results = src.search("PHP Developer", "Poland")
        assert results == []

    def test_non_polish_location_returns_empty_without_http(self):
        src = _build_source([_make_posting()])
        results = src.search("PHP Developer", "Germany")
        assert results == []
        src._get_listing_urls.assert_not_called()

    def test_remote_location_not_skipped(self):
        src = _build_source([_make_posting(city="", is_remote=True)])
        results = src.search("PHP Developer", "Remote")
        assert len(results) == 1

    def test_posting_fetch_failure_skips_offer(self):
        src = _build_source([_make_posting(slug="good"), _make_posting(slug="bad")])
        src._get_job_posting = MagicMock(
            side_effect=lambda u: None if "bad" in u else _make_posting()[1]
        )
        results = src.search("PHP Developer", "Poland")
        assert len(results) == 1
