# JobAgent

An AI-powered job search assistant that scrapes LinkedIn job listings and scores them using Claude. You tell it what you're looking for; it finds, filters, and ranks jobs for you.

## How it works

```
LinkedIn (Chrome) → collector → SQLite → Claude evaluator → Flask dashboard
```

1. **Collect** — opens Google Chrome, searches LinkedIn for configured search queries and locations, collects listings from the last N days. Results are sorted by date so the collector stops early once it hits a page of already-seen listings.
2. **Deduplicate** — skips jobs already seen (by URL and by title+company).
3. **Fetch descriptions** — visits each new job page and extracts the full description (batched with stealth delays between batches).
4. **Evaluate** — asks Claude to score each job 0–10 based on your criteria. Claude also learns from examples: jobs you applied to (positive) and jobs you rejected (negative).
5. **Auto-reject** — jobs with dealbreakers are immediately marked `auto_rejected` without needing manual review.
6. **Review** — browse scored results in a paginated web dashboard, mark jobs as `reviewed`, `applied`, or `rejected`.

### Job status flow

```
new → reviewed → applied
              ↘ rejected
auto_rejected  (set by evaluator automatically)
```

---

## Prerequisites

- Python 3.10+
- **Google Chrome** installed (the agent drives your system Chrome, not a bundled browser)
- An [Anthropic API key](https://console.anthropic.com/)
- A LinkedIn account

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd JobAgent
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create `.env` with your API key

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Adapt the candidate profile to yourself

Open `evaluator/scorer.py` and edit the `_CANDIDATE_PROFILE` constant at the top of the file. This is what Claude uses to evaluate every job — make it match your stack, experience level, location, and employment preferences.

```python
_CANDIDATE_PROFILE = """
CANDIDATE:
- Senior PHP Engineer, 8+ years experience
- Stack: PHP 8, Symfony, Laravel, ...
""".strip()
```

Also review the **AUTOMATIC REJECTION** rules in `build_system_prompt()` and adjust them to your situation (e.g. which countries/regions are off-limits for you).

### 4. Start the dashboard and set your search criteria

```bash
python web/app.py
```

Open `http://localhost:5000` and go to the **Criteria** tab. Add your search criteria before running the agent for the first time — **without at least one title and one location the agent will find nothing**.

| Criteria type | What it does | Example |
|---------------|-------------|---------|
| `search_query` | Query sent to LinkedIn search | `Senior PHP Developer remote` |
| `title` | Job title used for scoring only (not searched) | `Senior PHP Developer` |
| `location` | Location to search | `Poland`, `Remote` |
| `required` | Must appear in job description | `PHP 8`, `remote` |
| `preferred` | Nice to have — boosts score | `Symfony`, `Kubernetes` |
| `rejected` | Custom auto-rejection rule | `must be based in the UK` |

`search_query` is what gets sent to LinkedIn's search box. `title` is only used by Claude when scoring — useful when your actual job title differs from what you'd type in a search bar.

You can add, toggle, and delete criteria from the dashboard at any time. The **CV** tab lets you upload a PDF résumé and have Claude suggest search queries, titles, and keywords automatically.

---

## Running the agent

### From the dashboard (recommended)

Click **▶ Run Agent** in the dashboard. A log panel opens and streams output live. You can set:
- **Days back** — how far back to search (default: 1)
- **Max jobs** — cap on new jobs per run (default: unlimited)
- **Search query / location overrides** — run a one-off search without changing your saved criteria

While the agent is running a green **Running** indicator appears in the header. Click it at any time to open the **Activity** modal and see live logs — even if you started the run from the scheduler rather than the dashboard.

If there are jobs missing descriptions (fetched without a full description on the first pass), a **Fetch missing descriptions** button appears in the toolbar.

### From the CLI

```bash
# Full pipeline: collect then score
python scripts/run_all.py
python scripts/run_all.py --days 3 --max-jobs 20

# Collect only
python collector/runner.py --days 3 --max-jobs 20
python collector/runner.py --search-queries "Senior PHP Developer" "PHP Engineer" --locations "Poland" "Remote"

# Score only (run after the collector)
python evaluator/runner.py

# Backfill missing descriptions
python scripts/backfill_descriptions.py
```

### First run — LinkedIn login

On first launch, Chrome opens and pauses at the LinkedIn login screen. **Log in manually.** Your session is saved to `data/chrome_profile/` and reused on all subsequent runs — you only need to do this once (until the session expires).

---

## Reviewing results

Open `http://localhost:5000`. Jobs are sorted by score (highest first) and paginated (25 per page). For each job you can:

- **Open on LinkedIn** — read the full posting
- **Mark as reviewed** — you've read it, not yet applied
- **Mark as applied** — records the application; the job becomes a positive few-shot example for future evaluations
- **Reject** — removes it from the main feed; the job becomes a negative few-shot example for future evaluations

The more you apply/reject, the better Claude's scores get over time (few-shot learning).

---

## Scoring

Claude scores each job 0–10. The prompt includes:

- Your candidate profile (from `evaluator/scorer.py`)
- Active `required` criteria — job must mention all of them
- Active `preferred` criteria — each match raises the score
- Active `rejected` rules — any match triggers auto-rejection
- Up to 8 jobs you applied to (positive few-shot examples)
- Up to 5 jobs you manually rejected (negative few-shot examples)

`auto_rejected` jobs are never used as few-shot examples — they were machine-rejected, not a personal preference signal.

---

## Running tests

```bash
pytest
```

No API key or browser required — the test suite uses an in-memory SQLite database and mocks all Claude API calls.

```
tests/
  conftest.py                     # shared fixtures: temp DB, Flask test client
  unit/
    test_filters.py               # apply_filters() — keyword filtering logic
    test_scorer.py                # build_system_prompt(), prompt builder helpers
  integration/
    test_job_repository.py        # insert, dedup, get_unscored, search, stats
    test_criteria_repository.py   # CRUD, toggle, get_active_dict
    test_web_routes.py            # Flask endpoints: jobs, criteria, agent status
    test_evaluator_runner.py      # evaluator flow with mocked score_job
```

---

## Project structure

```
JobAgent/
├── config.py                     # API key, model, stealth settings
├── collector/
│   ├── base.py                   # JobSource ABC + RawJob dataclass
│   ├── filters.py                # Keyword-based pre-filter
│   ├── runner.py                 # Phase 1: search cards; Phase 2: fetch descriptions in batches
│   └── sources/
│       └── linkedin.py           # LinkedIn scraper (Playwright + system Chrome, anti-detection)
├── evaluator/
│   ├── scorer.py                 # Claude prompt builder + scoring logic  ← edit candidate profile here
│   └── runner.py                 # Score unscored jobs, auto-reject by rules
├── db/
│   ├── connection.py             # SQLite connection factory
│   ├── migrations.py             # CREATE TABLE IF NOT EXISTS schema
│   └── repositories/
│       ├── job_repository.py     # jobs CRUD + URL-set for dedup
│       ├── criteria_repository.py # criteria CRUD + toggle
│       └── session_repository.py  # run session tracking
├── scripts/
│   ├── run_all.py                # Full pipeline: collect → evaluate (scheduler entry point)
│   └── backfill_descriptions.py  # Retry fetching descriptions for jobs that missed them
├── web/
│   ├── app.py                    # Flask app, blueprint registration
│   ├── routes/
│   │   ├── jobs.py               # GET /api/jobs, POST /api/jobs/<id>/status, GET /api/stats
│   │   ├── criteria.py           # GET/POST /api/criteria, toggle, delete
│   │   ├── cv.py                 # CV upload, parse, suggest criteria
│   │   └── runner.py             # /api/agent/status, /api/agent/logs, /ws/agent, /ws/backfill
│   ├── templates/
│   │   └── dashboard.html
│   └── static/
│       ├── dashboard.js
│       └── dashboard.css
├── tests/                        # pytest test suite
├── pytest.ini
└── data/                         # All local data — gitignored
    ├── agent.db                  # SQLite database (auto-created)
    ├── chrome_profile/           # Persistent Chrome session (auto-created)
    └── logs/
        └── current_run.log       # Log from the most recent run (overwritten each run)
```

---

## Troubleshooting

**Agent finds no jobs** — check that you have at least one `title` and one `location` in the Criteria tab.

**Scraping breaks / wrong jobs returned** — LinkedIn occasionally changes its HTML. Update the CSS selectors in `collector/sources/linkedin.py` (look for `.job-card-list__title--link`, `.artdeco-entity-lockup__subtitle`, `.scaffold-layout__list-item`).

**`overloaded` error from Claude** — the evaluator retries automatically (up to 3 times, 30s/60s wait). If it keeps failing, try again later.

**LinkedIn session expired** — delete `data/chrome_profile/` and log in again on the next run.

**Dashboard shows "Running" but nothing is actually running** — a session may have been left in `status='running'` after a crash. The indicator auto-clears after 6 hours, or you can update the DB directly: `UPDATE sessions SET status='error' WHERE status='running'`.

**Jobs missing descriptions** — if the collector was interrupted during Phase 2, some jobs may have no description and therefore no score. Click the **Fetch missing descriptions** button in the dashboard toolbar to retry them.
