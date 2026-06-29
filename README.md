# JobAgent

An AI-powered job search assistant that scrapes LinkedIn job listings and scores them using Claude. You tell it what you're looking for; it finds, filters, and ranks jobs for you.

## How it works

```
LinkedIn (Chrome) → scraper → SQLite → Claude evaluator → Flask dashboard
```

1. **Scrape** — opens Google Chrome, searches LinkedIn for configured job titles and locations, collects listings from the last N days.
2. **Deduplicate** — skips jobs already seen (by URL and by title+company).
3. **Evaluate** — fetches each job's full description, asks Claude to score it 0–10 based on your criteria. Claude also learns from examples: jobs you applied to (positive) and jobs you rejected (negative).
4. **Auto-reject** — jobs with dealbreakers are immediately marked `auto_rejected` without needing manual review.
5. **Review** — browse scored results in a web dashboard, mark jobs as `reviewed`, `applied`, or `rejected`.

### Job status flow

```
new → reviewed → applied
              ↘ rejected
auto_rejected  (set by agent automatically)
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

Open `src/evaluator.py` and find the system prompt around line 98. Edit the **CANDIDATE** section to match your profile — your stack, experience level, location, and employment preferences. This is what Claude uses to evaluate every job.

```python
return f"""You are evaluating job listings for a Senior PHP Engineer based in Poland, working fully remote.

CANDIDATE:
- Senior PHP Engineer, 8+ years experience
- Stack: PHP 8, Symfony, Laravel, ...
```

Also review the **AUTOMATIC REJECTION** rules below it and adjust them to your situation (e.g. which countries/regions are off-limits for you).

### 4. Start the dashboard and set your search criteria

```bash
python src/web/app.py
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

```bash
python src/agent.py
python src/agent.py --days 3 --max-jobs 20
python src/agent.py --titles "Senior PHP Developer" "PHP Engineer" --locations "Poland" "Remote"
```

On macOS, wrap with `caffeinate -i` to prevent sleep during a long run:

```bash
caffeinate -i python src/agent.py
```

### First run — LinkedIn login

On first launch, Chrome opens and pauses at the LinkedIn login screen. **Log in manually.** Your session is saved to `data/chrome_profile/` and reused on all subsequent runs — you only need to do this once (until the session expires).

---

## Reviewing results

Open `http://localhost:5000`. Jobs are sorted by score (highest first). For each job you can:

- **Open on LinkedIn** — read the full posting
- **Mark as reviewed** — you've read it, not yet applied
- **Mark as applied** — records the application; the job is added as a positive example for future Claude evaluations
- **Reject** — removes it from the main feed; the job and your implicit reasoning become a negative example for future evaluations

The more you apply/reject, the better Claude's scores get over time (few-shot learning).

---

## (Optional) Seed positive examples

If you already applied to jobs on LinkedIn before setting up JobAgent, create `data/seed_urls.txt` with one URL per line. These are imported on the first agent run as positive few-shot examples.

```
# data/seed_urls.txt  (gitignored — stays local)
https://www.linkedin.com/jobs/view/1234567890/
https://www.linkedin.com/jobs/view/0987654321/
```

---

## Generate a standalone HTML report

```bash
python src/reporter.py
```

Saves a self-contained HTML file to `data/reports/` and opens it in the browser. Useful for sharing or archiving a snapshot of your job search.

---

## Project structure

```
JobAgent/
├── config.py                   # LinkedIn URL, agent paths, model name
├── src/
│   ├── agent.py                # Main loop: scrape → insert → evaluate
│   ├── browser.py              # Chrome automation: login, search, pagination
│   ├── evaluator.py            # Claude prompt + scoring + retry logic  ← edit candidate profile here
│   ├── reporter.py             # HTML report generator
│   ├── import_examples.py      # Imports applied-job examples for few-shot learning
│   ├── seed_criteria.py        # One-time criteria seeding from config
│   └── web/
│       └── app.py              # Flask dashboard + WebSocket agent runner
└── data/                       # All local data — gitignored
    ├── agent.db                # SQLite database (auto-created)
    ├── chrome_profile/         # Persistent Chrome session (auto-created)
    ├── seed_urls.txt           # Your pre-existing applied jobs (optional)
    └── reports/                # Generated HTML reports
```

---

## Scoring

Claude scores each job 0–10. The prompt includes:

- Your candidate profile (from `evaluator.py`)
- Active `required` criteria — job must mention all of them
- Active `preferred` criteria — each match raises the score
- Active `rejected` rules — any match triggers auto-rejection
- Up to 8 jobs you applied to (positive few-shot examples)
- Up to 5 jobs you manually rejected (negative few-shot examples)

`auto_rejected` jobs are never used as few-shot examples — they were machine-rejected, not a personal preference signal.

---

## Troubleshooting

**Agent finds no jobs** — check that you have at least one `title` and one `location` in the Criteria tab.

**Scraping breaks / wrong jobs returned** — LinkedIn occasionally changes its HTML. Update the CSS selectors in `src/browser.py` (look for `.job-card-list__title--link`, `.artdeco-entity-lockup__subtitle`, `.scaffold-layout__list-item`).

**`overloaded` error from Claude** — the agent retries automatically (up to 3 times, 30s/60s wait). If it keeps failing, try again later.

**LinkedIn session expired** — delete `data/chrome_profile/` and log in again on the next run.
