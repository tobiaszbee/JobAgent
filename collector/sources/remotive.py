"""Remotive.io source — free public JSON API, no auth required."""
from datetime import datetime, timedelta, timezone

import httpx

from collector.base import JobSource, RawJob
from collector.location import location_matches
from collector.utils import strip_html

_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(JobSource):
    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None
        self._jobs_cache: dict[str, list[dict]] = {}

    @property
    def name(self) -> str:
        return "remotive"

    def __enter__(self):
        self._client = httpx.Client(
            headers={"User-Agent": "JobAgent/1.0 (job aggregator)"},
            timeout=30,
            follow_redirects=True,
        )
        self._jobs_cache = {}
        return self

    def __exit__(self, *args):
        if self._client:
            self._client.close()
        self._client = None
        self._jobs_cache = {}

    def login(self) -> None:
        pass

    def _fetch_jobs(self, title: str) -> list[dict]:
        if title in self._jobs_cache:
            return self._jobs_cache[title]
        try:
            resp = self._client.get(_API_URL, params={"search": title, "limit": 0})
        except Exception:
            return []
        if resp.status_code != 200:
            return []
        jobs = resp.json().get("jobs", [])
        # Remotive searches full descriptions — keep only jobs where the keyword
        # appears in the title or tags, not just buried in the description.
        if title:
            keyword = title.lower()
            jobs = [
                j for j in jobs
                if keyword in j.get("title", "").lower()
                or any(keyword in t.lower() for t in j.get("tags", []))
            ]
        self._jobs_cache[title] = jobs
        return self._jobs_cache[title]

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
            if not location_matches(candidate_loc, location):
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
