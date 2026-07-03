"""We Work Remotely source — public RSS feed, no auth required."""
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import httpx

from collector.base import JobSource, RawJob

# ── Location constants (same vocabulary as remotive.py) ──────────────────────

_EU_COUNTRIES = frozenset({
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic",
    "denmark", "estonia", "finland", "france", "germany", "greece", "hungary",
    "ireland", "italy", "latvia", "lithuania", "luxembourg", "malta",
    "netherlands", "poland", "portugal", "romania", "slovakia", "slovenia",
    "spain", "sweden", "iceland", "liechtenstein", "norway", "switzerland",
    "united kingdom",
})

_WORLDWIDE_TOKENS = frozenset({"anywhere", "worldwide", "global", "world"})
_EUROPE_TOKENS = frozenset({"europe", "european", "emea", "eea", "eu"})
_NA_TOKENS = frozenset({"usa", "us only", "united states", "north america"})

_COUNTRY_ALIASES = {
    "us": "united states", "usa": "united states",
    "uk": "united kingdom", "gb": "united kingdom",
    "pl": "poland", "de": "germany", "fr": "france",
    "at": "austria", "ch": "switzerland", "nl": "netherlands",
    "cz": "czech republic",
}

_REMOTE_TERMS = frozenset({"remote", "zdalne", "zdalnie", "zdalny"})

# ── US states (to classify as USA-only) ──────────────────────────────────────
_US_STATES = frozenset({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
})


def _region_matches(wwr_region: str, search_location: str) -> bool:
    region = wwr_region.lower().strip()
    raw = search_location.lower().strip()
    loc = _COUNTRY_ALIASES.get(raw, raw)

    # Empty region → treat as worldwide
    if not region or any(t in region for t in _WORLDWIDE_TOKENS):
        return True

    # Europe-only → matches EU countries and "remote" searches
    if any(t in region for t in _EUROPE_TOKENS):
        return loc in _EU_COUNTRIES or loc in _REMOTE_TERMS

    # US-only (explicit or US state) → only match US/NA search locations
    is_us_region = any(t in region for t in _NA_TOKENS) or region in _US_STATES
    if is_us_region:
        return loc in ("united states", "canada") or (
            any(t in region for t in _NA_TOKENS) and loc in _REMOTE_TERMS
        )

    # Canada-only
    if "canada" in region and "only" in region:
        return loc == "canada"

    # Specific country named in region — check if search location matches
    if loc in region:
        return True
    # Reverse alias check
    aliases = [k for k, v in _COUNTRY_ALIASES.items() if v == loc]
    return any(a in region for a in aliases)


# ── HTML stripping ────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def text(self) -> str | None:
        return " ".join(" ".join(self._parts).split()).strip() or None


def _strip_html(html: str) -> str | None:
    if not html or not html.strip():
        return None
    p = _TextExtractor()
    p.feed(html)
    return p.text()


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_date(pub_date: str) -> datetime:
    return parsedate_to_datetime(pub_date)


# ── Source ────────────────────────────────────────────────────────────────────

class WWRSource(JobSource):
    stealth_pause = False
    _FEED_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"

    @property
    def name(self) -> str:
        return "weworkremotely"

    def search(
        self,
        title: str,
        location: str,
        days_back: int | None = None,
        max_results: int | None = None,
        known_urls: set | None = None,
    ) -> list[RawJob]:
        known_urls = known_urls or set()
        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(days=days_back)
            if days_back else None
        )

        try:
            response = httpx.get(
                self._FEED_URL,
                headers={"User-Agent": "JobAgent/1.0"},
                timeout=15,
                follow_redirects=True,
            )
            response.raise_for_status()
        except Exception:
            return []

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            return []

        results: list[RawJob] = []
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item"):
            # URL
            link = (item.findtext("link") or item.findtext("guid") or "").strip()
            if not link or link in known_urls:
                continue

            # Date filter
            pub_date_str = item.findtext("pubDate") or ""
            if cutoff and pub_date_str:
                try:
                    pub_dt = _parse_date(pub_date_str)
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    pass

            # Title → split into company + job_title
            raw_title = (item.findtext("title") or "").strip()
            if ": " in raw_title:
                company, job_title = raw_title.split(": ", 1)
            else:
                company, job_title = "", raw_title

            # Title keyword filter
            if title and title.lower() not in job_title.lower():
                continue

            # Location filter
            region = (item.findtext("region") or "").strip()
            if not _region_matches(region, location):
                continue

            # Description
            desc_html = item.findtext("description") or ""
            description = _strip_html(desc_html)

            results.append(RawJob(
                title=job_title,
                company=company,
                location=region or "Remote",
                url=link,
                source=self.name,
                source_id=link.rstrip("/").split("/")[-1],
                description=description,
            ))

            if max_results and len(results) >= max_results:
                break

        return results
