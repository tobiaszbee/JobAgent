"""NoFluffJobs source — Poland/CEE tech job board, public and unauthenticated.

No Cloudflare wall here (unlike theprotocol.it/it.pracuj.pl) — a plain `httpx` GET with
a realistic User-Agent works directly, verified live, so no Playwright is needed for
either search() or fetch_description().

This is an Angular Universal (SSR) app: listing and detail data are both embedded as
JSON in a `<script id="serverApp-state">` tag, Angular's TransferState mechanism. The
JSON text has a handful of HTML entities escaped (`&q;`, `&a;`, `&l;`, `&g;`) that must
be un-escaped before parsing. Keys are hashed or literal-request-path strings (Angular's
HTTP TransferState cache is keyed by request identity, not a fixed name) — rather than
guess the exact key, we scan all top-level values for the shape we need.

Search results don't include the full description (only tags/salary/seniority), so a
second GET to the job's detail page is made per new posting.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from collector.base import JobSource, RawJob
from collector.utils import strip_html

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://nofluffjobs.com/pl/{kw}"
_DETAIL_URL = "https://nofluffjobs.com/pl/job/{slug}"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
_POLAND_ALIASES = {"poland", "polska", "pl"}
_STATE_RE = re.compile(r'<script id="serverApp-state" type="application/json">(.*?)</script>', re.DOTALL)


def _parse_server_state(html: str) -> dict | None:
    import json
    m = _STATE_RE.search(html)
    if not m:
        return None
    raw = m.group(1).replace("&q;", '"').replace("&a;", "&").replace("&l;", "<").replace("&g;", ">")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _find_postings(state: dict) -> list[dict]:
    for value in state.values():
        if isinstance(value, dict):
            search_response = value.get("searchResponse")
            if isinstance(search_response, dict) and "postings" in search_response:
                return search_response.get("postings") or []
    return []


def _find_description(state: dict) -> str | None:
    for value in state.values():
        if isinstance(value, dict):
            details = value.get("details")
            if isinstance(details, dict) and "description" in details:
                return strip_html(details.get("description") or "")
    return None


class NoFluffJobsSource(JobSource):
    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None

    @property
    def name(self) -> str:
        return "nofluffjobs"

    def __enter__(self):
        self._client = httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True)
        return self

    def __exit__(self, *args):
        if self._client:
            self._client.close()
        self._client = None

    def fetch_description(self, url: str) -> str | None:
        try:
            resp = self._client.get(url)
        except Exception as e:
            logger.warning(f"NoFluffJobs detail fetch failed: {e}")
            return None
        if resp.status_code != 200:
            return None
        state = _parse_server_state(resp.text)
        if not state:
            return None
        return _find_description(state)

    def search(
        self,
        title: str,
        location: str,
        days_back: int | None = None,
        max_results: int | None = None,
        known_urls: set[str] | None = None,
    ) -> list[RawJob]:
        if location.strip().lower() not in _POLAND_ALIASES:
            return []
        if not title.strip():
            return []

        days = days_back if days_back is not None else self._days_back
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        url = _SEARCH_URL.format(kw=quote(title.strip()))
        try:
            resp = self._client.get(url, params={"criteria": "remote=remote"})
        except Exception as e:
            logger.warning(f"NoFluffJobs search request failed: {e}")
            return []
        if resp.status_code != 200:
            return []

        state = _parse_server_state(resp.text)
        if not state:
            return []

        postings = _find_postings(state)
        # Only the first page of results is fetched — plenty for a daily incremental
        # run; deeper pagination isn't implemented yet.

        results: list[RawJob] = []
        for posting in postings:
            if max_results and len(results) >= max_results:
                break

            slug = posting.get("url")
            if not slug:
                continue

            posted_ms = posting.get("posted")
            try:
                posted_dt = datetime.fromtimestamp(posted_ms / 1000, tz=timezone.utc) if posted_ms else None
            except (TypeError, ValueError, OSError):
                posted_dt = None
            if posted_dt and posted_dt < cutoff:
                continue

            job_url = _DETAIL_URL.format(slug=slug)
            if known_urls and job_url in known_urls:
                continue

            results.append(RawJob(
                title=posting.get("title", ""),
                company=posting.get("name", ""),
                location="Poland (Remote)",
                url=job_url,
                source=self.name,
                source_id=posting.get("id"),
                description=self.fetch_description(job_url),
            ))

        return results
