"""Remote OK source — public JSON API, no auth required."""
from datetime import datetime, timedelta, timezone

import httpx

from collector.base import JobSource, RawJob
from collector.location import location_matches
from collector.utils import strip_html

_API_URL = "https://remoteok.io/api"



class RemoteOKSource(JobSource):
    requires_stealth_pauses = False

    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None
        self._jobs_cache: list[dict] | None = None

    @property
    def name(self) -> str:
        return "remoteok"

    def __enter__(self):
        self._client = httpx.Client(
            headers={"User-Agent": "JobAgent/1.0 (job aggregator)"},
            timeout=30,
            follow_redirects=True,
        )
        self._jobs_cache = None
        return self

    def __exit__(self, *args):
        if self._client:
            self._client.close()
        self._client = None
        self._jobs_cache = None

    def login(self) -> None:
        pass

    def _fetch_jobs(self) -> list[dict]:
        if self._jobs_cache is not None:
            return self._jobs_cache
        try:
            resp = self._client.get(_API_URL)
        except Exception:
            return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        if not isinstance(data, list) or len(data) < 2:
            return []
        # First element is API metadata, not a job — skip it
        self._jobs_cache = [item for item in data[1:] if isinstance(item, dict)]
        return self._jobs_cache

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
            if keyword and keyword not in position.lower():
                continue

            job_location = job.get("location", "") or ""
            if not location_matches(job_location, location):
                continue

            results.append(RawJob(
                title=position,
                company=job.get("company", ""),
                location=job_location or "Remote",
                url=url,
                source="remoteok",
                source_id=job.get("slug", ""),
                description=strip_html(job.get("description", "")),
            ))

        return results
