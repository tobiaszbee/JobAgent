"""Working Nomads source — public JSON API, no auth required."""
import re
from datetime import datetime, timedelta, timezone

import httpx

from collector.base import JobSource, RawJob

_API_URL  = "https://www.workingnomads.com/api/exposed_jobs/?category=development"
_BASE_URL = "https://www.workingnomads.com"


def _canonical_url(url: str) -> str:
    if url.startswith("http"):
        return url
    return _BASE_URL + (url if url.startswith("/") else f"/{url}")


def _strip_html(html: str) -> str | None:
    if not html:
        return None
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


class WorkingNomadsSource(JobSource):
    stealth_pause = False

    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None

    @property
    def name(self) -> str:
        return "workingnomads"

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
        return data if isinstance(data, list) else []

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

            pub_str = job.get("pub_date", "")
            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            except (ValueError, AttributeError):
                continue

            raw_url = job.get("url", "")
            if not raw_url:
                continue
            url = _canonical_url(raw_url)
            if known_urls and url in known_urls:
                continue

            job_title = job.get("title", "")
            tag_names = [
                t["name"].lower()
                for t in job.get("tags", [])
                if isinstance(t, dict) and "name" in t
            ]
            if keyword not in job_title.lower() and not any(keyword in t for t in tag_names):
                continue

            results.append(RawJob(
                title=job_title,
                company=job.get("company_name", ""),
                location=job.get("location", "") or "Remote",
                url=url,
                source="workingnomads",
                source_id=str(job.get("id", "")),
                description=_strip_html(job.get("description", "")),
            ))

        return results
