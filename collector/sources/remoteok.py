"""Remote OK source — public JSON API, no auth required."""
import re
from datetime import datetime, timedelta, timezone

import httpx

from collector.base import JobSource, RawJob

_API_URL = "https://remoteok.io/api"

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


def _location_matches(job_location: str, search_location: str) -> bool:
    req = job_location.lower()
    raw = search_location.lower().strip()
    loc = _COUNTRY_ALIASES.get(raw, raw)

    if loc in _REMOTE_TERMS:
        return True
    if not req or any(t in req for t in _WORLDWIDE_TOKENS):
        return True
    if loc in _EU_COUNTRIES and any(t in req for t in _EUROPE_TOKENS):
        return True
    if loc in ("united states", "canada") and any(t in req for t in _NA_TOKENS):
        return True
    if loc in req:
        return True
    aliases = [k for k, v in _COUNTRY_ALIASES.items() if v == loc]
    return any(a in req for a in aliases)


def _strip_html(html: str) -> str | None:
    if not html:
        return None
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


class RemoteOKSource(JobSource):
    stealth_pause = False

    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None

    @property
    def name(self) -> str:
        return "remoteok"

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

    def _fetch_jobs(self) -> list[dict]:
        resp = self._client.get(_API_URL)
        if resp.status_code != 200:
            return []
        data = resp.json()
        # First element is API metadata, not a job — skip it
        return [item for item in data[1:] if isinstance(item, dict)]

    def search(
        self,
        title: str,
        location: str,
        days_back: int | None = None,
        max_results: int | None = None,
        known_urls: set[str] | None = None,
    ) -> list[RawJob]:
        days    = days_back if days_back is not None else self._days_back
        cutoff  = datetime.now(timezone.utc) - timedelta(days=days)
        keyword = title.lower()

        jobs = self._fetch_jobs()

        results: list[RawJob] = []
        for job in jobs:
            if max_results and len(results) >= max_results:
                break

            date_str = job.get("date", "")
            try:
                pub_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
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

            position = job.get("position", "")
            tags = [t.lower() for t in job.get("tags", []) if isinstance(t, str)]
            if keyword not in position.lower() and not any(keyword in t for t in tags):
                continue

            job_location = job.get("location", "") or ""
            if not _location_matches(job_location, location):
                continue

            results.append(RawJob(
                title=position,
                company=job.get("company", ""),
                location=job_location or "Remote",
                url=url,
                source="remoteok",
                source_id=job.get("slug", ""),
                description=_strip_html(job.get("description", "")),
            ))

        return results
