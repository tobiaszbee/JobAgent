"""Unit tests for the JustJoin.it source — no HTTP calls made."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from collector.sources.justjoin import (
    JustJoinSource,
    _match_location,
    _match_query,
    _strip_html,
    _format_location,
)


# ── helper functions ───────────────────────────────────────────────────────────

class TestMatchLocation:
    def _offer(self, city="Warsaw", country="PL", remote=False, remote_interview=False):
        return {"city": city, "country_code": country,
                "remote": remote, "remote_interview": remote_interview}

    def test_poland_matches_pl_country(self):
        assert _match_location(self._offer(country="PL"), "Poland")

    def test_poland_does_not_match_de(self):
        assert not _match_location(self._offer(country="DE"), "Poland")

    def test_city_substring_match(self):
        assert _match_location(self._offer(city="Warsaw"), "Warsaw")

    def test_city_case_insensitive(self):
        assert _match_location(self._offer(city="Warsaw"), "warsaw")

    def test_city_no_match(self):
        assert not _match_location(self._offer(city="Kraków"), "Warsaw")

    def test_remote_match_on_remote_flag(self):
        assert _match_location(self._offer(remote=True), "Remote")

    def test_remote_match_on_remote_interview_flag(self):
        assert _match_location(self._offer(remote_interview=True), "Remote")

    def test_remote_no_match_for_non_remote(self):
        assert not _match_location(self._offer(remote=False), "Remote")


class TestMatchQuery:
    def _offer(self, title="PHP Developer", skills=None):
        return {
            "title": title,
            "skills": [{"name": s} for s in (skills or [])],
        }

    def test_matches_technology_in_title(self):
        assert _match_query(self._offer("PHP Developer"), "PHP Developer")

    def test_matches_technology_in_skills(self):
        assert _match_query(self._offer("Backend Developer", skills=["PHP"]), "PHP Developer")

    def test_no_match_different_technology(self):
        assert not _match_query(self._offer("Java Engineer", skills=["Java"]), "PHP Developer")

    def test_generic_words_excluded(self):
        # "Senior Developer" → filtered to empty → falls back to exact title check
        offer = self._offer("Java Developer")
        # "Senior Developer" has no tech keyword, falls back — should not match Java title
        assert not _match_query(offer, "Senior Developer")

    def test_multi_word_any_match(self):
        assert _match_query(self._offer("PHP Symfony Engineer"), "Symfony Backend")

    def test_case_insensitive(self):
        assert _match_query(self._offer("php developer"), "PHP")


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


class TestFormatLocation:
    def test_city_only(self):
        offer = {"city": "Warsaw", "remote": False, "remote_interview": False}
        assert _format_location(offer, "Poland") == "Warsaw"

    def test_remote_only(self):
        offer = {"city": "", "remote": True, "remote_interview": False}
        assert _format_location(offer, "Poland") == "Remote"

    def test_city_and_remote(self):
        offer = {"city": "Kraków", "remote": True, "remote_interview": False}
        assert _format_location(offer, "Poland") == "Kraków / Remote"

    def test_fallback_when_no_city(self):
        offer = {"city": "", "remote": False, "remote_interview": False}
        assert _format_location(offer, "Poland") == "Poland"


# ── JustJoinSource.search() with mocked HTTP ─────────────────────────────────

def _make_offer(
    offer_id="acme-php-dev-warsaw",
    title="PHP Developer",
    company="Acme",
    city="Warsaw",
    country="PL",
    remote=False,
    skills=None,
    body=None,
    days_ago=0,
):
    pub = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "id": offer_id,
        "title": title,
        "company_name": company,
        "city": city,
        "country_code": country,
        "remote": remote,
        "remote_interview": False,
        "published_at": pub,
        "skills": [{"name": s} for s in (skills or ["PHP"])],
        "body": body or "",
    }


def _mock_client(offers: list[dict], detail_bodies: dict[str, str] | None = None):
    """Return a mock httpx.Client that serves offers list and optional detail bodies."""
    detail_bodies = detail_bodies or {}

    def _get(url, **_):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if url.endswith("/offers"):
            resp.json.return_value = offers
        elif "/offers/" in url:
            offer_id = url.split("/offers/")[-1]
            resp.json.return_value = {"body": detail_bodies.get(offer_id, "")}
        return resp

    client = MagicMock()
    client.get.side_effect = _get
    return client


class TestJustJoinSourceSearch:
    def _source(self, offers, detail_bodies=None, days_back=7):
        src = JustJoinSource(days_back=days_back)
        src._client = _mock_client(offers, detail_bodies)
        src._cache = None
        return src

    def test_returns_matching_offer(self):
        offer = _make_offer()
        src = self._source([offer])
        results = src.search("PHP Developer", "Poland")
        assert len(results) == 1
        assert results[0].title == "PHP Developer"
        assert results[0].source == "justjoin"

    def test_filters_by_location(self):
        pl_offer = _make_offer(offer_id="pl-job", city="Warsaw", country="PL")
        de_offer = _make_offer(offer_id="de-job", city="Berlin", country="DE")
        src = self._source([pl_offer, de_offer])
        results = src.search("PHP Developer", "Poland")
        assert len(results) == 1
        assert results[0].source_id == "pl-job"

    def test_filters_by_days_back(self):
        recent = _make_offer(offer_id="recent", days_ago=1)
        old    = _make_offer(offer_id="old",    days_ago=10)
        src = self._source([recent, old], days_back=7)
        results = src.search("PHP Developer", "Poland")
        assert len(results) == 1
        assert results[0].source_id == "recent"

    def test_skips_known_urls(self):
        offer = _make_offer()
        known = {"https://justjoin.it/job-offer/acme-php-dev-warsaw"}
        src = self._source([offer])
        results = src.search("PHP Developer", "Poland", known_urls=known)
        assert results == []

    def test_respects_max_results(self):
        offers = [_make_offer(offer_id=f"job-{i}", title="PHP Developer") for i in range(10)]
        src = self._source(offers)
        results = src.search("PHP Developer", "Poland", max_results=3)
        assert len(results) == 3

    def test_uses_body_from_list_when_present(self):
        offer = _make_offer(body="<p>Great job</p>")
        src = self._source([offer])
        results = src.search("PHP Developer", "Poland")
        assert results[0].description == "Great job"

    def test_fetches_detail_when_body_absent(self):
        offer = _make_offer(body="")
        src = self._source([offer], detail_bodies={"acme-php-dev-warsaw": "<p>Detail desc</p>"})
        with patch("collector.sources.justjoin.time.sleep"):  # skip courtesy delay
            results = src.search("PHP Developer", "Poland")
        assert results[0].description == "Detail desc"

    def test_description_none_when_no_body_anywhere(self):
        offer = _make_offer(body="")
        src = self._source([offer], detail_bodies={})
        with patch("collector.sources.justjoin.time.sleep"):
            results = src.search("PHP Developer", "Poland")
        assert results[0].description is None

    def test_url_format(self):
        offer = _make_offer(offer_id="acme-php-dev-warsaw")
        src = self._source([offer])
        results = src.search("PHP Developer", "Poland")
        assert results[0].url == "https://justjoin.it/job-offer/acme-php-dev-warsaw"

    def test_offers_cached_across_searches(self):
        # body present → no detail fetch; both searches share one list call
        offer = _make_offer(body="<p>desc</p>")
        src = self._source([offer])
        src.search("PHP Developer", "Poland")
        src.search("PHP Developer", "Remote")
        assert src._client.get.call_count == 1  # list fetched only once

    def test_remote_location(self):
        offer = _make_offer(city="Warsaw", remote=True)
        src = self._source([offer])
        results = src.search("PHP Developer", "Remote")
        assert len(results) == 1
        assert "Remote" in results[0].location
