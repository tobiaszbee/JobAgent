"""Unit tests for the We Work Remotely RSS source — no real HTTP calls made."""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock

from collector.sources.weworkremotely import WWRSource, _region_matches


class TestRegionMatches:
    def test_empty_region_matches_all(self):
        assert _region_matches("", "Poland")

    def test_worldwide_matches_any_country(self):
        assert _region_matches("Anywhere in the World", "Germany")

    def test_europe_matches_eu_country(self):
        assert _region_matches("Europe Only", "Poland")

    def test_europe_does_not_match_us(self):
        assert not _region_matches("Europe Only", "United States")

    def test_us_only_matches_united_states(self):
        assert _region_matches("USA Only", "United States")

    def test_us_only_does_not_match_poland(self):
        assert not _region_matches("USA Only", "Poland")

    def test_named_country_matches(self):
        assert _region_matches("Poland, Ukraine", "Poland")


def _item_xml(
    link="https://weworkremotely.com/remote-jobs/acme-php-developer",
    title="Acme: PHP Developer",
    region="Anywhere in the World",
    description="<p>Great role</p>",
    days_ago=0,
) -> str:
    pub_date = format_datetime(datetime.now(timezone.utc) - timedelta(days=days_ago))
    return f"""
        <item>
            <title>{title}</title>
            <link>{link}</link>
            <pubDate>{pub_date}</pubDate>
            <region>{region}</region>
            <description><![CDATA[{description}]]></description>
        </item>
    """


def _feed_xml(items: list[str]) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
            <title>We Work Remotely</title>
            {"".join(items)}
        </channel></rss>
    """


def _build_source(items_xml: list[str], days_back: int = 7) -> WWRSource:
    src = WWRSource(days_back=days_back)
    src._feed_cache = None
    root = ET.fromstring(_feed_xml(items_xml))
    src._fetch_items = MagicMock(return_value=root.find("channel").findall("item"))
    return src


class TestWWRSourceSearch:
    def test_returns_matching_job(self):
        src = _build_source([_item_xml()])
        results = src.search("PHP Developer", "Remote")
        assert len(results) == 1
        assert results[0].title == "PHP Developer"
        assert results[0].company == "Acme"
        assert results[0].source == "weworkremotely"

    def test_title_without_colon_has_no_company(self):
        src = _build_source([_item_xml(title="Just A Title No Colon")])
        results = src.search("Title", "Remote")
        assert results[0].company == ""
        assert results[0].title == "Just A Title No Colon"

    def test_source_id_from_link(self):
        src = _build_source([_item_xml(link="https://weworkremotely.com/remote-jobs/acme-php-1")])
        results = src.search("PHP Developer", "Remote")
        assert results[0].source_id == "acme-php-1"

    def test_filters_by_keyword_in_title(self):
        php = _item_xml(title="Acme: PHP Developer", link="https://weworkremotely.com/remote-jobs/1")
        py  = _item_xml(title="Acme: Python Developer", link="https://weworkremotely.com/remote-jobs/2")
        src = _build_source([php, py])
        results = src.search("PHP", "Remote")
        assert len(results) == 1
        assert results[0].title == "PHP Developer"

    def test_filters_by_region(self):
        eu = _item_xml(region="Europe Only", link="https://weworkremotely.com/remote-jobs/1")
        us = _item_xml(region="USA Only", link="https://weworkremotely.com/remote-jobs/2")
        src = _build_source([eu, us])
        results = src.search("Developer", "Poland")
        assert len(results) == 1
        assert results[0].url.endswith("/1")

    def test_skips_known_urls(self):
        src = _build_source([_item_xml(link="https://weworkremotely.com/remote-jobs/dup")])
        known = {"https://weworkremotely.com/remote-jobs/dup"}
        results = src.search("PHP Developer", "Remote", known_urls=known)
        assert results == []

    def test_filters_by_date(self):
        fresh = _item_xml(link="https://weworkremotely.com/remote-jobs/fresh", days_ago=1)
        old   = _item_xml(link="https://weworkremotely.com/remote-jobs/old", days_ago=30)
        src = _build_source([fresh, old], days_back=7)
        results = src.search("Developer", "Remote")
        assert len(results) == 1
        assert results[0].url.endswith("/fresh")

    def test_respects_max_results(self):
        items = [_item_xml(link=f"https://weworkremotely.com/remote-jobs/{i}") for i in range(5)]
        src = _build_source(items)
        results = src.search("Developer", "Remote", max_results=2)
        assert len(results) == 2

    def test_description_stripped(self):
        src = _build_source([_item_xml(description="<p>Good <b>role</b></p>")])
        results = src.search("Developer", "Remote")
        assert results[0].description == "Good role"

    def test_empty_feed_returns_empty(self):
        src = _build_source([])
        results = src.search("Developer", "Remote")
        assert results == []

    def test_posted_at_captures_the_publication_date(self):
        # pubDate was already parsed for the days_back cutoff, then discarded —
        # RawJob.posted_at carries it through instead.
        src = _build_source([_item_xml(days_ago=3)])
        results = src.search("PHP Developer", "Remote")
        assert results[0].posted_at is not None
        posted = datetime.fromisoformat(results[0].posted_at)
        assert (datetime.now(timezone.utc) - posted).days == 3

    def test_missing_pub_date_never_crashes_and_posted_at_is_none(self):
        item = """
            <item>
                <title>Acme: PHP Developer</title>
                <link>https://weworkremotely.com/remote-jobs/no-date</link>
                <region>Anywhere in the World</region>
                <description>Great role</description>
            </item>
        """
        src = _build_source([item])
        results = src.search("PHP Developer", "Remote")
        assert len(results) == 1
        assert results[0].posted_at is None
