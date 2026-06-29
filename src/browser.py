import time
import random
import os
import sys
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import AGENT, LINKEDIN


class Browser:
    def __init__(self, extra_search_params="&f_WT=2&f_TPR=r604800"):
        self._playwright = None
        self._browser = None
        self._page = None
        self._extra_search_params = extra_search_params

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch_persistent_context(
            user_data_dir=os.path.join(ROOT, "data", "chrome_profile"),
            channel="chrome",
            headless=AGENT["headless"],
            viewport={"width": 1280, "height": 800}
        )
        if self._browser.pages:
            self._page = self._browser.pages[-1]
        else:
            self._page = self._browser.new_page()

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _wait(self, min_sec=2, max_sec=8):
        time.sleep(random.uniform(min_sec, max_sec))

    def _scroll_to_bottom(self):
        # randomized scroll to mimic human behavior
        scroll_pos = 0
        while True:
            scroll_height = self._page.evaluate("() => document.body.scrollHeight")
            if scroll_pos >= scroll_height:
                break
            scroll_pos = min(scroll_pos + random.randint(300, 700), scroll_height)
            self._page.evaluate(f"window.scrollTo(0, {scroll_pos})")
            time.sleep(random.uniform(0.2, 0.7))

    def goto(self, url):
        try:
            self._page.goto(url, wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeout:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._wait()

    def wait_for_login(self):
        self._page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=30_000)
        if "feed" in self._page.url or "jobs" in self._page.url:
            return
        print("Please log in to LinkedIn in the browser window...")
        self._page.wait_for_url("**/feed/**", timeout=120_000)
        print("Logged in!")
        self._wait()

    def search_jobs(self, title, location, max_jobs=None):
        url = (
            f"{LINKEDIN['search_url']}"
            f"?keywords={quote(title)}"
            f"&location={quote(location)}"
            f"{self._extra_search_params}"
        )
        self.goto(url)
        self._wait()
        return self._collect_job_cards(max_jobs=max_jobs)

    def _collect_job_cards(self, max_jobs=None):
        all_jobs = []
        page_num = 0

        while True:
            try:
                self._page.wait_for_selector(".scaffold-layout__list-item", timeout=10_000)
            except PlaywrightTimeout:
                print("No results found or page structure changed.")
                break

            self._scroll_to_bottom()

            jobs = self._page.evaluate("""
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

            all_jobs.extend(jobs)
            page_num += 1
            print(f"  Page {page_num}: {len(jobs)} jobs (total: {len(all_jobs)})")

            if max_jobs and len(all_jobs) >= max_jobs:
                break

            next_btn = self._page.query_selector("button[aria-label='View next page']")
            if not next_btn:
                break

            next_btn.click()
            self._wait(min_sec=5, max_sec=12)

        return all_jobs[:max_jobs] if max_jobs else all_jobs

    def get_job_description(self, url):
        self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            self._page.wait_for_load_state("networkidle", timeout=8_000)
        except PlaywrightTimeout:
            time.sleep(3)

        self._scroll_to_bottom()
        self._wait(min_sec=8, max_sec=20)  # anti-detection: simulate reading time

        return self._page.evaluate("""
            () => {
                const body = document.body.innerText;
                const idx = body.indexOf('About the job');
                if (idx !== -1) return body.slice(idx, idx + 5000).trim();
                return '';
            }
        """)

    def get_page_title_company(self):
        return self._page.evaluate("""
            () => {
                const parts = (document.title || '').split(' | ');
                return { title: parts[0]?.trim() || '', company: parts[1]?.trim() || '' };
            }
        """)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


if __name__ == "__main__":
    from src.db.repositories.criteria_repository import get_criteria_dict
    criteria = get_criteria_dict()

    with Browser() as browser:
        browser.wait_for_login()

        title    = criteria["titles"][0] if criteria["titles"] else "PHP Developer"
        location = criteria["locations"][0] if criteria["locations"] else "Remote"

        print(f"\nSearching: {title} in {location}")
        jobs = browser.search_jobs(title, location)

        print(f"\nFound {len(jobs)} jobs:")
        for job in jobs[:5]:
            print(f"  {job['title']} @ {job['company']} — {job['location']}")
            print(f"  {job['url']}")

        if jobs:
            print(f"\nFetching description for first job...")
            desc = browser.get_job_description(jobs[0]["url"])
            print(f"Length: {len(desc)} chars")
            print(f"Preview: {desc[:300]}...")
