import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import AGENT
from src.browser import Browser
from src.db.migrations import run as init_db
from src.db.connection import get_connection

_SEED_FILE = os.path.join(ROOT, AGENT.get("seed_urls_path", "data/seed_urls.txt"))


def _load_seed_urls():
    if not os.path.exists(_SEED_FILE):
        return []
    with open(_SEED_FILE) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def already_imported(url):
    conn = get_connection()
    row = conn.execute("SELECT id FROM examples WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row is not None


def save_example(url, title, company, description):
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO examples (url, title, company, description) VALUES (?, ?, ?, ?)",
        (url, title, company, description)
    )
    conn.commit()
    conn.close()


def get_pending_urls():
    """
    Returns URLs that need to be imported:
    1. Seed URLs from data/seed_urls.txt
    2. Jobs marked as 'applied' in the jobs table but not yet in examples
    """
    conn = get_connection()
    applied_urls = [
        row["url"] for row in conn.execute(
            "SELECT url FROM jobs WHERE status = 'applied'"
        ).fetchall()
    ]
    conn.close()

    all_urls = list(set(_load_seed_urls() + applied_urls))
    return [url for url in all_urls if not already_imported(url)]


def _import_pending(browser, pending):
    for i, url in enumerate(pending):
        print(f"\n[{i+1}/{len(pending)}] {url}")
        description = browser.get_job_description(url)
        meta = browser.get_page_title_company()
        save_example(url, meta["title"], meta["company"], description)
        print(f"  Saved: {meta['title']} @ {meta['company']} ({len(description)} chars)")


def run(browser=None):
    """
    Import pending examples.
    browser: existing Browser instance to reuse. If None, opens a new one.
    """
    init_db()
    pending = get_pending_urls()

    if not pending:
        print("All examples already imported.")
        return

    print(f"Importing {len(pending)} examples...")

    if browser:
        _import_pending(browser, pending)
    else:
        with Browser() as b:
            b.wait_for_login()
            _import_pending(b, pending)

    print(f"\nDone! {len(pending)} examples imported.")


if __name__ == "__main__":
    run()
