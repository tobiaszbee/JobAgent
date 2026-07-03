"""Remotive.io source — free public JSON API, no auth required."""
from datetime import datetime, timedelta, timezone

import httpx

from collector.base import JobSource, RawJob
from collector.utils import strip_html

_API_URL = "https://remotive.com/api/remote-jobs"

_EU_COUNTRIES = frozenset({
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic",
    "denmark", "estonia", "finland", "france", "germany", "greece", "hungary",
    "ireland", "italy", "latvia", "liechtenstein", "lithuania", "luxembourg",
    "malta", "netherlands", "norway", "poland", "portugal", "romania",
    "slovakia", "slovenia", "spain", "sweden", "switzerland", "united kingdom",
})

_WORLDWIDE_TOKENS = frozenset({"worldwide", "anywhere", "global", "international"})
_EUROPE_TOKENS    = frozenset({"europe", "european", "emea", "eea", "eu "})
_NA_TOKENS        = frozenset({"north america", "usa/canada", "canada/usa", "americas"})

_COUNTRY_ALIASES: dict[str, str] = {
    "us":            "united states",
    "usa":           "united states",
    "u.s.":          "united states",
    "uk":            "united kingdom",
    "gb":            "united kingdom",
    "great britain": "united kingdom",
    "deutschland":   "germany",
    "polska":        "poland",
    "pl":            "poland",
}

_REMOTE_TERMS = frozenset({"remote", "zdalne", "zdalnie", "zdalny"})


def _location_matches(candidate_required_location: str, search_location: str) -> bool:
    req = candidate_required_location.lower()
    raw = search_location.lower().strip()
    loc = _COUNTRY_ALIASES.get(raw, raw)

    # All Remotive jobs are remote — "Remote" in search criteria matches everything
    if loc in _REMOTE_TERMS:
        return True

    # Job open to everyone
    if any(t in req for t in _WORLDWIDE_TOKENS):
        return True

    # Job requires Europe — match any European country
    if loc in _EU_COUNTRIES and any(t in req for t in _EUROPE_TOKENS):
        return True

    # Job requires North America — match US or Canada
    if loc in ("united states", "canada") and any(t in req for t in _NA_TOKENS):
        return True

    # Direct match: normalized name OR any known alias appears in requirements
    if loc in req:
        return True
    aliases = [k for k, v in _COUNTRY_ALIASES.items() if v == loc]
    return any(a in req for a in aliases)


class RemotiveSource(JobSource):
    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None

    @property
    def name(self) -> str:
        return "remotive"

    def __enter__(self):
        self._client = httpx.Client(
            headers={"User-Agent": "JobAgent/1.0 (job aggregator)"},
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

    def _fetch_jobs(self, title: str) -> list[dict]:
        resp = self._client.get(_API_URL, params={"search": title, "limit": 0})
        if resp.status_code != 200:
            return []
        return resp.json().get("jobs", [])

    def search(
        self,
        title: str,
        location: str,
        days_back: int | None = None,
        max_results: int | None = None,
        known_urls: set[str] | None = None,
    ) -> list[RawJob]:
        days   = days_back if days_back is not None else self._days_back
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        jobs = self._fetch_jobs(title)

        results: list[RawJob] = []
        for job in jobs:
            if max_results and len(results) >= max_results:
                break

            # Date filter
            pub_str = job.get("publication_date", "")
            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            except (ValueError, AttributeError):
                continue

            url = job.get("url", "")
            if not url:
                continue
            if known_urls and url in known_urls:
                continue

            candidate_loc = job.get("candidate_required_location", "")
            if not _location_matches(candidate_loc, location):
                continue

            results.append(RawJob(
                title=job.get("title", ""),
                company=job.get("company_name", ""),
                location=candidate_loc or "Remote",
                url=url,
                source="remotive",
                source_id=str(job.get("id", "")),
                description=strip_html(job.get("description", "")),
            ))

        return results
