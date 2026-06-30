# JobAgent

An AI-powered job search assistant that scrapes LinkedIn job listings and scores them using Claude. You tell it what you're looking for; it finds, filters, and ranks jobs for you.

## How it works

```
LinkedIn (Chrome) → collector → SQLite → Claude evaluator → Flask dashboard
```

1. **Collect** — opens Google Chrome, searches LinkedIn for configured job titles and locations, collects listings from the last N days and fetches their full descriptions.
2. **Deduplicate** — skips jobs already seen (by URL and by title+company).
3. **Evaluate** — asks Claude to score each job 0–10 based on your criteria. Claude also learns from examples: jobs you applied to (positive) and jobs you rejected (negative).
4. **Auto-reject** — jobs with dealbreakers are immediately marked `auto_rejected` without needing manual review.
5. **Review** — browse scored results in a web dashboard, mark jobs as `reviewed`, `applied`, or `rejected`.

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
| `title` | Job title to search on LinkedIn | `Senior PHP Developer` |
| `location` | Location to search | `Poland`, `Remote` |
| `required` | Must appear in job description | `PHP 8`, `remote` |
| `preferred` | Nice to have — boosts score | `Symfony`, `Kubernetes` |
| `rejected` | Custom auto-rejection rule | `must be based in the UK` |

You can add, toggle, and delete criteria from the dashboard at any time.

---

## Running the agent

### From the dashboard (recommended)

Click **Run Agent** in the dashboard. A log panel opens and streams output live. You can set:
- **Days back** — how far back to search (default: 7)
- **Max jobs** — cap on new jobs per run (default: unlimited)
- **Title / location overrides** — run a one-off search without changing your saved criteria

### From the CLI

Run the collector and evaluator separately:

```bash
# Collect new jobs from LinkedIn
python collector/runner.py
python collector/runner.py --days 3 --max-jobs 20
python collector/runner.py --titles "Senior PHP Developer" "PHP Engineer" --locations "Poland" "Remote"

# Score all unscored jobs (run after the collector)
python evaluator/runner.py
```

### First run — LinkedIn login

On first launch, Chrome opens and pauses at the LinkedIn login screen. **Log in manually.** Your session is saved to `data/chrome_profile/` and reused on all subsequent runs — you only need to do this once (until the session expires).

---

## Reviewing results

Open `http://localhost:5000`. Jobs are sorted by score (highest first). For each job you can:

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
├── config.py                     # API key, model, paths
├── collector/
│   ├── base.py                   # JobSource ABC + RawJob dataclass
│   ├── filters.py                # Keyword-based pre-filter
│   ├── runner.py                 # CLI entry point: search → insert → fetch descriptions
│   └── sources/
│       └── linkedin.py           # LinkedIn scraper (Playwright + system Chrome)
├── evaluator/
│   ├── scorer.py                 # Claude prompt builder + scoring logic  ← edit candidate profile here
│   └── runner.py                 # CLI entry point: score unscored jobs
├── db/
│   ├── connection.py             # SQLite connection factory
│   ├── migrations.py             # CREATE TABLE IF NOT EXISTS schema
│   └── repositories/
│       ├── job_repository.py     # jobs CRUD
│       ├── criteria_repository.py # criteria CRUD + toggle
│       └── session_repository.py  # run session tracking
├── web/
│   ├── app.py                    # Flask app, blueprint registration
│   ├── routes/
│   │   ├── jobs.py               # GET /api/jobs, POST /api/jobs/<id>/status, GET /api/stats
│   │   ├── criteria.py           # GET/POST /api/criteria, toggle, delete
│   │   └── runner.py             # GET /api/agent/status, WebSocket /ws/agent
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
    └── reports/                  # (reserved for future report generation)
```

---

## Troubleshooting

**Agent finds no jobs** — check that you have at least one `title` and one `location` in the Criteria tab.

**Scraping breaks / wrong jobs returned** — LinkedIn occasionally changes its HTML. Update the CSS selectors in `collector/sources/linkedin.py` (look for `.job-card-list__title--link`, `.artdeco-entity-lockup__subtitle`, `.scaffold-layout__list-item`).

**`overloaded` error from Claude** — the evaluator retries automatically (up to 3 times, 30s/60s wait). If it keeps failing, try again later.

**LinkedIn session expired** — delete `data/chrome_profile/` and log in again on the next run.
