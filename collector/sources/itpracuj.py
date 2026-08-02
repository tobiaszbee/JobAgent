"""it.pracuj.pl source — Poland's largest general job board, IT section.

Same corporate group (Grupa Pracuj) and Cloudflare setup as theprotocol.it: a plain
`httpx` GET gets a "Just a moment..." challenge, and even headless Playwright
(`channel="chrome"`) gets served the same challenge. Only a non-headless (visible)
browser gets through — verified live. So, like theprotocol.it, this source uses
Playwright end to end, no login/stealth pacing (public site, no account).

Unlike theprotocol.it, the `kw` search parameter here is a genuine substring/keyword
filter, not a single-technology-tag autocomplete — "symfony developer" (4 results) is a
proper subset of bare "symfony" (11 results), verified live. So the full multi-word
`title` is passed through as-is, no first-word tag extraction needed.

Search results embed a short, truncated description preview (`jobDescription`, ends in
"..."). The full description lives on the job's detail page (`offerAbsoluteUri`), on a
*different* subdomain (www.pracuj.pl vs. it.pracuj.pl for search) — and navigating there
in the same browser session, right after a search-page load, triggered a real Cloudflare
CAPTCHA challenge live (not just the usual auto-clearing "Just a moment" screen). Since
bypassing a CAPTCHA is off the table, this deliberately does NOT do a second fetch: the
truncated `jobDescription` preview from search results is used as-is. It's shorter than
ideal but real, substantive content — good enough for scoring, without the CAPTCHA risk.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from collector.base import JobSource, RawJob
from collector.location import workplace_suffix

logger = logging.getLogger(__name__)

# No "praca%20zdalna;wm,home-office" (remote-only) URL segment: it.pracuj.pl is
# routed for hybrid/onsite Polish-city candidates too (see collector/runner.py's
# _POLAND_ONLY_SOURCES routing), so hardcoding remote-only here silently
# returned nothing relevant for them.
_SEARCH_URL = "https://it.pracuj.pl/praca/{kw};kw"
_POLAND_ALIASES = {"poland", "polska", "pl"}
_WORK_MODE_TOKENS = {
    "praca zdalna": "remote",
    "praca hybrydowa": "hybrid",
    "praca stacjonarna": "onsite",
}


def _read_next_data(page) -> dict | None:
    try:
        # state="attached": a <script> tag is never "visible" (wait_for_selector's
        # default), it just needs to exist in the DOM.
        page.wait_for_selector("#__NEXT_DATA__", state="attached", timeout=10_000)
        raw = page.eval_on_selector("#__NEXT_DATA__", "el => el.textContent")
    except PlaywrightTimeout:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _find_query(data: dict, query_name: str) -> dict | None:
    queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    for q in queries:
        key = q.get("queryKey")
        if key and key[0] == query_name:
            return q.get("state", {}).get("data")
    return None


class ItPracujSource(JobSource):
    # Same Grupa Pracuj / Cloudflare setup as theprotocol.it — multiple back-to-back
    # searches with zero pause triggered a live Cloudflare challenge mid-run. Opting
    # into LinkedIn's adaptive pause between searches fixes it.
    requires_stealth_pauses = True

    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._playwright = None
        self._browser = None
        self._page = None

    @property
    def name(self) -> str:
        return "itpracuj"

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(channel="chrome", headless=False)
        self._page = self._browser.new_page()
        return self

    def __exit__(self, *args):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._page = None

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
            self._page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except PlaywrightTimeout:
            logger.warning(f"it.pracuj.pl search timed out for title={title!r}")
            return []

        data = _read_next_data(self._page)
        if not data:
            return []

        job_offers = _find_query(data, "jobOffers") or {}
        grouped = job_offers.get("groupedOffers", [])
        # Only the first page (default 50 grouped results) is fetched — plenty for a
        # daily incremental run; deeper pagination isn't implemented yet.

        results: list[RawJob] = []
        for group in grouped:
            if max_results and len(results) >= max_results:
                break

            offers = group.get("offers") or []
            if not offers:
                continue
            offer_url = offers[0].get("offerAbsoluteUri")
            if not offer_url:
                continue

            pub_str = group.get("lastPublicated")
            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00")) if pub_str else None
            except ValueError:
                pub_dt = None
            if pub_dt and pub_dt < cutoff:
                continue

            if known_urls and offer_url in known_urls:
                continue

            city = offers[0].get("displayWorkplace")
            modes = {_WORK_MODE_TOKENS.get(m.lower()) for m in (group.get("workModes") or [])}
            modes.discard(None)
            location_str = f"{city}, Poland{workplace_suffix(modes)}" if city else f"Poland{workplace_suffix(modes)}"

            results.append(RawJob(
                title=group.get("jobTitle", ""),
                company=group.get("companyName", ""),
                location=location_str,
                url=offer_url,
                source=self.name,
                source_id=str(offers[0].get("partitionId") or group.get("groupId") or ""),
                description=group.get("jobDescription") or None,
            ))

        return results
