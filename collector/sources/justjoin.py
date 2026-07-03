"""
JustJoin.it scraper.

Data strategy:
  - Listing page (/job-offers/all-locations/{tech}) — JSON-LD CollectionPage
    with one entry per offer (URL only).  Fetched once per search() call.
  - Detail page (/job-offer/{slug}) — JSON-LD JobPosting with title, company,
    location, datePosted, and full description.  Fetched only for unknown URLs.
"""

import json
import re
import time
import httpx
from datetime import datetime, timedelta, timezone

from collector.base import JobSource, RawJob
from collector.utils import strip_html

_BASE = "https://justjoin.it"

# Maps query keywords → JustJoin category slug
_TECH_MAP: dict[str, str] = {
    "php": "php",
    "python": "python",
    "javascript": "javascript", "js": "javascript",
    "typescript": "javascript", "ts": "javascript",
    "react": "javascript", "vue": "javascript",
    "angular": "javascript", "node": "javascript",
    "java": "java",
    "ruby": "ruby",
    "scala": "scala",
    ".net": "net", "c#": "net", "csharp": "net",
    "go": "go", "golang": "go",
    "rust": "rust",
    "kotlin": "kotlin",
    "swift": "swift",
    "c++": "c", "cpp": "c",
    "backend": "backend",
    "frontend": "frontend",
    "fullstack": "fullstack",
    "devops": "devops",
    "data": "data", "analytics": "data",
    "ai": "ai", "machine learning": "ai", "ml": "ai",
    "mobile": "mobile", "android": "mobile", "ios": "mobile",
    "testing": "testing", "qa": "testing",
    "security": "security",
    "ux": "ux",
}


def _tech_slug(query: str) -> str:
    q = query.lower()
    for keyword, slug in _TECH_MAP.items():
        if keyword in q:
            return slug
    return "all-locations"


def _match_location(city: str, country: str, is_remote: bool, location: str) -> bool:
    loc = location.lower().strip()
    if loc in ("remote", "zdalne", "zdalnie", "zdalny"):
        return is_remote
    if loc in ("poland", "polska", "pl"):
        return country.lower() in ("poland", "pl", "polska")
    city_l = city.lower()
    return loc in city_l or city_l in loc


def _extract_ld_json(html: str, target_type: str) -> dict | None:
    for match in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            d = json.loads(match.group(1))
            if d.get("@type") == target_type:
                return d
        except (json.JSONDecodeError, AttributeError):
            pass
    return None


class JustJoinSource(JobSource):
    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None

    @property
    def name(self) -> str:
        return "justjoin"

    def __enter__(self):
        self._client = httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
            timeout=30,
            follow_redirects=True,
        )
        return self

    def __exit__(self, *args):
        if self._client:
            self._client.close()
        self._client = None

    def login(self) -> None:
        pass

    def _get_listing_urls(self, tech_slug: str) -> list[str]:
        url = f"{_BASE}/job-offers/all-locations" + (f"/{tech_slug}" if tech_slug != "all-locations" else "")
        resp = self._client.get(url)
        if resp.status_code != 200:
            return []
        data = _extract_ld_json(resp.text, "CollectionPage")
        if data:
            return [item["url"] for item in data.get("hasPart", []) if "url" in item]
        return []

    def _get_job_posting(self, url: str) -> dict | None:
        time.sleep(0.2)
        resp = self._client.get(url)
        if resp.status_code != 200:
            return None
        return _extract_ld_json(resp.text, "JobPosting")

    def search(
        self,
        title: str,
        location: str,
        days_back: int | None = None,
        max_results: int | None = None,
        known_urls: set[str] | None = None,
    ) -> list[RawJob]:
        loc = location.lower().strip()
        if loc not in ("poland", "polska", "pl", "remote", "zdalne", "zdalnie", "zdalny"):
            return []

        days = days_back if days_back is not None else self._days_back
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        slug = _tech_slug(title)
        urls = self._get_listing_urls(slug)

        results: list[RawJob] = []
        for url in urls:
            if max_results and len(results) >= max_results:
                break
            if known_urls is not None and url in known_urls:
                continue

            posting = self._get_job_posting(url)
            if not posting:
                continue

            # Date filter
            date_str = posting.get("datePosted", "")
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass

            # Location
            addr = posting.get("jobLocation", {}).get("address", {})
            city = addr.get("addressLocality", "")
            country_req = posting.get("applicantLocationRequirements") or {}
            if isinstance(country_req, list):
                country_req = country_req[0] if country_req else {}
            country = country_req.get("name", "")
            is_remote = posting.get("jobLocationType", "").upper() == "TELECOMMUTE"

            if not _match_location(city, country, is_remote, location):
                continue

            if city and is_remote:
                loc_str = f"{city} / Remote"
            elif is_remote:
                loc_str = "Remote"
            else:
                loc_str = city or location

            desc_html = posting.get("description", "")
            results.append(RawJob(
                title=posting.get("title", ""),
                company=(posting.get("hiringOrganization") or {}).get("name", ""),
                location=loc_str,
                url=url,
                source="justjoin",
                source_id=url.split("/job-offer/")[-1],
                description=strip_html(desc_html) if desc_html else None,
            ))

        return results
