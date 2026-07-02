import re
import time
import httpx
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from collector.base import JobSource, RawJob

_BASE = "https://justjoin.it"
_API  = "https://justjoin.it/api"

_GENERIC_WORDS = {
    "developer", "engineer", "senior", "junior", "mid", "lead",
    "staff", "principal", "manager", "specialist", "architect",
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "li", "br", "h1", "h2", "h3", "h4", "h5", "div", "tr"}:
            self._parts.append("\n")

    def get_text(self) -> str:
        raw = "".join(self._parts)
        lines = (ln.strip() for ln in raw.splitlines())
        return "\n".join(ln for ln in lines if ln)


def _strip_html(html: str) -> str:
    ex = _TextExtractor()
    ex.feed(html)
    return ex.get_text()


def _match_location(offer: dict, location: str) -> bool:
    loc = location.lower().strip()
    if loc in ("remote", "zdalne", "zdalnie", "zdalny"):
        return bool(offer.get("remote_interview") or offer.get("remote"))
    city = (offer.get("city") or "").lower()
    country = (offer.get("country_code") or "").lower()
    if loc in ("poland", "polska", "pl"):
        return country == "pl"
    # simple substring match in both directions handles diacritics mismatch
    return loc in city or city in loc


def _match_query(offer: dict, query: str) -> bool:
    offer_title = (offer.get("title") or "").lower()
    skills_text = " ".join(s.get("name", "").lower() for s in (offer.get("skills") or []))
    target = f"{offer_title} {skills_text}"

    keywords = [
        w.lower() for w in re.split(r"\W+", query)
        if len(w) >= 3 and w.lower() not in _GENERIC_WORDS
    ]
    if not keywords:
        return query.lower() in offer_title
    return any(kw in target for kw in keywords)


def _format_location(offer: dict, fallback: str) -> str:
    city = offer.get("city") or offer.get("company_city") or ""
    remote = bool(offer.get("remote_interview") or offer.get("remote"))
    if city and remote:
        return f"{city} / Remote"
    if remote:
        return "Remote"
    return city or fallback


class JustJoinSource(JobSource):
    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None
        self._cache: list[dict] | None = None

    @property
    def name(self) -> str:
        return "justjoin"

    def __enter__(self):
        self._client = httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"},
            timeout=30,
            follow_redirects=True,
        )
        return self

    def __exit__(self, *args):
        if self._client:
            self._client.close()
        self._client = None
        self._cache = None

    def login(self) -> None:
        pass

    def _all_offers(self) -> list[dict]:
        if self._cache is None:
            resp = self._client.get(f"{_API}/offers")
            resp.raise_for_status()
            self._cache = resp.json()
        return self._cache

    def _fetch_body(self, offer_id: str) -> str | None:
        try:
            resp = self._client.get(f"{_API}/offers/{offer_id}")
            resp.raise_for_status()
            html = resp.json().get("body") or ""
            return _strip_html(html) if html else None
        except Exception:
            return None

    def search(
        self,
        title: str,
        location: str,
        days_back: int | None = None,
        max_results: int | None = None,
        known_urls: set[str] | None = None,
    ) -> list[RawJob]:
        days = days_back if days_back is not None else self._days_back
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        results: list[RawJob] = []

        for offer in self._all_offers():
            pub = offer.get("published_at")
            if pub:
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass

            if not _match_location(offer, location):
                continue
            if not _match_query(offer, title):
                continue

            offer_id = offer.get("id", "")
            url = f"{_BASE}/job-offer/{offer_id}"

            if known_urls is not None and url in known_urls:
                continue

            # Description: use `body` from list if present, else fetch detail
            body = offer.get("body") or ""
            if not body:
                body = self._fetch_body(offer_id) or ""
                time.sleep(0.3)  # courtesy delay for detail fetches

            results.append(RawJob(
                title=offer["title"],
                company=offer.get("company_name", ""),
                location=_format_location(offer, location),
                url=url,
                source="justjoin",
                source_id=offer_id,
                description=_strip_html(body) if body else None,
            ))

            if max_results and len(results) >= max_results:
                break

        return results
