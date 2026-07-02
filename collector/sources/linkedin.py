import time
import random
import os
import sys
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import AGENT, LINKEDIN, STEALTH
from collector.base import JobSource, RawJob

_SEARCH_URL = LINKEDIN["search_url"]

# Pages visited between job batches to simulate organic browsing
_DISTRACTION_URLS = [
    "https://www.linkedin.com/feed/",
    "https://www.linkedin.com/mynetwork/",
    "https://www.linkedin.com/jobs/",
]


class LinkedInSource(JobSource):
    def __init__(self, days_back: int = 7):
        self._days_back = days_back
        self._playwright = None
        self._browser = None
        self._page = None

    @property
    def name(self) -> str:
        return "linkedin"

    # --- lifecycle ---

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch_persistent_context(
            user_data_dir=os.path.join(ROOT, "data", "chrome_profile"),
            channel="chrome",
            headless=AGENT["headless"],
            viewport={"width": 1280, "height": 800},
        )
        self._page = self._browser.pages[-1] if self._browser.pages else self._browser.new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    # --- public API ---

    def login(self) -> None:
        """Navigate to LinkedIn and wait for manual login if session has expired."""
        self._goto("https://www.linkedin.com/login")
        if "feed" in self._page.url or "jobs" in self._page.url:
            return
        print("Please log in to LinkedIn in the browser window...")
        self._page.wait_for_url("**/feed/**", timeout=120_000)
        print("Logged in.")
        self._wait()

    def search(self, title: str, location: str, days_back: int | None = None, max_results: int | None = None) -> list[RawJob]:
        days = days_back if days_back is not None else self._days_back
        seconds = days * 24 * 3600
        url = (
            f"{_SEARCH_URL}"
            f"?keywords={quote(title)}"
            f"&location={quote(location)}"
            f"&f_WT=2"
            f"&f_TPR=r{seconds}"
        )
        self._goto(url)
        self._wait()
        return self._collect_cards(max_jobs=max_results)

    def fetch_description(self, url: str) -> str | None:
        self._jitter_mouse()
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except PlaywrightTimeout:
            return None
        try:
            self._page.wait_for_load_state("networkidle", timeout=8_000)
        except PlaywrightTimeout:
            time.sleep(3)

        self._jitter_mouse()
        self._scroll_to_bottom()
        # Occasionally scroll back up a bit — like re-reading something
        if random.random() < 0.3:
            up = random.randint(200, 600)
            self._page.evaluate(f"window.scrollBy(0, -{up})")
            time.sleep(random.uniform(1, 3))
            self._scroll_to_bottom()

        self._human_delay(
            STEALTH["desc_delay_min"],
            STEALTH["desc_delay_max"],
        )

        return self._page.evaluate("""
            () => {
                // Try LinkedIn's structured description element first (prefer longer content)
                const descEl = document.querySelector('.jobs-description__content, .jobs-box__html-content, .description__text');
                const descText = descEl ? descEl.innerText.trim() : '';
                if (descText.length > 100) {
                    return descText.slice(0, 5000);
                }
                // Fall back to section header — multilingual
                const headers = [
                    'About the job', 'Über die Stelle', 'À propos du poste',
                    'Over de functie', 'Sobre el trabajo', 'O tej pracy',
                    'Om jobbet', 'Tietoja työpaikasta', 'Om stillingen',
                ];
                const body = document.body.innerText;
                for (const h of headers) {
                    const idx = body.indexOf(h);
                    if (idx !== -1) return body.slice(idx, idx + 5000).trim();
                }
                // Last resort: use whatever the structured element found, even if short
                if (descText.length > 0) return descText.slice(0, 5000);
                return '';
            }
        """) or None

    def distract(self) -> None:
        """Visit a random non-job LinkedIn page to simulate organic browsing."""
        url = random.choice(_DISTRACTION_URLS)
        print(f"  [stealth] Visiting {url}")
        try:
            self._goto(url)
        except Exception:
            return
        self._jitter_mouse()
        self._scroll_to_bottom()
        self._human_delay(15, 45)

    # --- private helpers ---

    def _human_delay(self, min_sec: float, max_sec: float) -> float:
        """Beta-distributed delay: mostly short, occasionally long. 5% chance of extra 1-5 min pause."""
        r = random.betavariate(2, 5)   # peaks near 0.25 of range
        wait = min_sec + r * (max_sec - min_sec)
        if random.random() < 0.05:     # 5% — "went to make coffee"
            wait += random.uniform(60, 300)
        time.sleep(wait)
        return wait

    def _jitter_mouse(self) -> None:
        """Move mouse to a few random positions to simulate natural cursor movement."""
        try:
            vw = self._page.viewport_size or {"width": 1280, "height": 800}
            w, h = vw["width"], vw["height"]
            steps = random.randint(2, 5)
            for _ in range(steps):
                x = random.randint(100, w - 100)
                y = random.randint(100, h - 100)
                self._page.mouse.move(x, y)
                time.sleep(random.uniform(0.1, 0.4))
        except Exception:
            pass

    def _goto(self, url: str) -> None:
        try:
            self._page.goto(url, wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeout:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    def _wait(self, min_sec: float = 2, max_sec: float = 8) -> None:
        time.sleep(random.uniform(min_sec, max_sec))

    def _scroll_to_bottom(self) -> None:
        scroll_pos = 0
        while True:
            scroll_height = self._page.evaluate("() => document.body.scrollHeight")
            if scroll_pos >= scroll_height:
                break
            scroll_pos = min(scroll_pos + random.randint(300, 700), scroll_height)
            self._page.evaluate(f"window.scrollTo(0, {scroll_pos})")
            time.sleep(random.uniform(0.2, 0.8))

    def _collect_cards(self, max_jobs: int | None = None) -> list[RawJob]:
        results: list[RawJob] = []
        page_num = 0

        while True:
            try:
                self._page.wait_for_selector(".scaffold-layout__list-item", timeout=10_000)
            except PlaywrightTimeout:
                print("  No results found or LinkedIn page structure changed.")
                break

            self._scroll_to_bottom()

            cards = self._page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('.scaffold-layout__list-item');
                    const results = [];
                    cards.forEach(card => {
                        const titleEl    = card.querySelector('.job-card-list__title--link');
                        const companyEl  = card.querySelector('.artdeco-entity-lockup__subtitle span');
                        const locationEl = card.querySelector('.job-card-container__metadata-wrapper li span');
                        if (!titleEl) return;
                        const href = titleEl.getAttribute('href');
                        if (!href) return;
                        const footerText = card.innerText || '';
                        if (footerText.includes('Applied') || footerText.includes('Application submitted')) return;
                        results.push({
                            title:    titleEl.innerText.trim().split('\\n')[0].trim(),
                            company:  companyEl  ? companyEl.innerText.trim()  : '',
                            location: locationEl ? locationEl.innerText.trim() : '',
                            url:      'https://www.linkedin.com' + href.split('?')[0],
                        });
                    });
                    return results;
                }
            """)

            for card in cards:
                results.append(RawJob(
                    title=card["title"],
                    company=card["company"],
                    location=card["location"],
                    url=card["url"],
                    source=self.name,
                ))

            page_num += 1
            print(f"  Page {page_num}: {len(cards)} cards (total: {len(results)})")

            if max_jobs and len(results) >= max_jobs:
                break

            next_btn = self._page.query_selector("button[aria-label='View next page']")
            if not next_btn:
                break

            next_btn.click()
            self._wait(min_sec=5, max_sec=15)

        return results[:max_jobs] if max_jobs else results
