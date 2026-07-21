# JobAgent

An AI-powered job search assistant that collects remote job listings, ranks them with a multi-stage AI pipeline, and learns your preferences from your apply/reject decisions over time.

---

## Table of Contents

1. [How it works — overview](#how-it-works--overview)
2. [Setup](#setup)
3. [User manual — step by step](#user-manual--step-by-step)
4. [Dashboard reference](#dashboard-reference)
5. [Technical deep-dive](#technical-deep-dive)
6. [Project structure](#project-structure)
7. [Running tests](#running-tests)
8. [Troubleshooting](#troubleshooting)

---

## How it works — overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  COLLECTION                                                             │
│  LinkedIn + job boards → keyword filter → fetch descriptions → SQLite  │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ new jobs with descriptions
┌──────────────────────────────▼──────────────────────────────────────────┐
│  AI PIPELINE (per Run Agent)                                            │
│                                                                         │
│  1. Distill preferences   ← your apply/reject history                  │
│          │                                                              │
│  2. Score (Sonnet)        ← CV + preferences + few-shot examples       │
│          │                                                              │
│  3. Extract structure     ← Haiku: remote? seniority? stack? salary?   │
│          │                                                              │
│  4. Embed (Voyage)        ← 1024-dim vector per job                    │
│          │                                                              │
│  5. Semantic retrieval    ← ideal vector = centroid(applied)           │
│          │                   − 0.3 × centroid(rejected)                │
│          │                                                              │
│  6. Cross-encoder rerank  ← Voyage rerank-2: top-50 → top-20          │
│          │                                                              │
│  7. Listwise rank (Opus)  ← extended thinking, orders top-20          │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ scored + ranked jobs
┌──────────────────────────────▼──────────────────────────────────────────┐
│  DASHBOARD                                                              │
│  Browse → apply / reject → feedback loop → better rankings next time   │
└─────────────────────────────────────────────────────────────────────────┘
```

Each run makes the next one smarter: your decisions feed the preference distiller, which shapes scoring and ranking.

---

## Setup

### Prerequisites

- Python 3.10+
- Google Chrome (for LinkedIn scraping)
- [Anthropic API key](https://console.anthropic.com/) — Claude Sonnet, Haiku, Opus
- [Voyage AI API key](https://www.voyageai.com/) — embeddings + reranker
- A LinkedIn account

### Installation

```bash
git clone <repo-url>
cd JobAgent
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### Environment

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...
```

### Start the dashboard

```bash
python web/app.py
```

Open `http://localhost:5000`.

---

## User manual — step by step

### Step 1 — Upload your CV

Go to the **CV** tab. Upload a PDF résumé. Claude parses it into a structured candidate profile that is injected into every scoring prompt. It also suggests initial search queries and keywords based on your experience.

Do this once. Re-upload only if your CV changes significantly.

### Step 2 — Configure criteria

Go to the **Criteria** tab. You need at least:
- One **Search Query** or **Job Title** (e.g. `Senior Python Developer`) — Search Query takes priority if both are set
- One **Location** (e.g. `Poland`, `Remote`, `Europe`)

| Type | Effect | Example |
|------|--------|---------|
| `search_query` | Sent as the literal search phrase (wrapped in quotes for LinkedIn to force exact-phrase matching). Takes priority over `title` — if none are active, `title` criteria are used as the search phrase instead | `Senior Python Developer` |
| `title` | Fallback search phrase when no `search_query` is active (shown as "using Job Titles" in the Run Agent modal) | `Senior PHP Developer` |
| `location` | Combined with each search phrase | `Remote`, `Poland` |
| `rejected` | Keyword anywhere in the title → skips the description fetch entirely; keyword in title+description → auto-rejected | `wordpress`, `ruby` |
| `required` | None present anywhere in title+description → auto-rejected (hard filter). If present, also shown to Sonnet as scoring context | `php`, `python` |
| `preferred` | Shown to Sonnet as soft scoring context only — never auto-rejects anything | `Docker`, `Symfony` |

Sources (LinkedIn, Remotive, RemoteOK, Working Nomads, WeWorkRemotely) aren't Criteria-tab items — pick which ones to use per run in the **Run Agent** modal.

**On phrasing `search_query`/`title` values:** LinkedIn matching behavior here is not obvious — quotes force an exact literal phrase, word order changes results completely, and a bare language name (`PHP`, `Python`) alone outperforms compound phrases (`PHP Developer`, `Senior PHP Engineer`). See [How LinkedIn keyword search actually behaves](#how-linkedin-keyword-search-actually-behaves) before adding new phrases — it's easy to add something that looks reasonable and either finds nothing or reintroduces noise.

### Step 3 — First Run Agent

Click **▶ Run Agent** in the header. A modal lets you configure:
- **Days back** — how far to look (1 = today's listings)
- **Sources** — which boards to search
- **Locations / Search queries** — override saved criteria for this run only

The pipeline runs in order:
1. Collect jobs from configured sources
2. Distill preferences from your history (skipped on first run — no history yet)
3. Score new jobs with Claude Sonnet
4. Extract structured data (remote/hybrid, seniority, stack, salary, company type)
5. Embed jobs with Voyage and rank them

**First run — LinkedIn login:** Chrome opens and pauses at the LinkedIn login screen. Log in manually. Your session is saved to `data/chrome_profile/` and reused on all future runs.

### Step 4 — Review jobs

After the run, browse the **New** tab. For each job:

- Click the title to open the original posting
- Expand **Show description** to read it without leaving the dashboard
- Use the action buttons:

| Button | What it does |
|--------|-------------|
| **Reviewed** | You've read it; staying visible but not yet decided |
| **Applied ✓** | You applied; becomes a positive example for future scoring |
| **Reject ✗** | Opens a reason box; becomes a negative example |

**Tip:** Write a rejection reason — e.g. "stawka za niska", "outsourcing body shop", "too junior". These are included verbatim in the preference distillation prompt and directly influence what Opus extracts as signals.

**Bulk actions:** Click **Bulk actions** in the toolbar to enter selection mode. Select multiple cards, then apply a status to all at once. For bulk reject, a shared reason input appears.

### Step 5 — Filter and search

The toolbar offers several ways to narrow the list:

- **Search bar** — searches title, company, location, description, and AI reasoning text simultaneously
- **Min score** — hide jobs below a score threshold
- **Sort** — AI rank (default), score, date, or company
- **Badge filters** — click any badge on a job card (remote, senior, startup, python…) to filter by it. Multiple badges = AND. Active filters appear as chips above the job list.

### Step 6 — Second run and beyond

After you've reviewed a batch:

1. Click **▶ Run Agent** again (or just **⟳ Re-score new** if you only want to re-score with updated preferences without collecting new jobs)
2. The distiller runs first — it reads your decisions and updates the preference profile
3. New jobs get scored and ranked using your updated profile
4. The AI rank badge (`#N`) on each card shows the Opus listwise position

**The loop:** every apply/reject decision improves the next ranking. After ~20–30 decisions the preference profile becomes meaningful. After ~50+ it converges.

### Step 7 — Other actions

| Button | When to use |
|--------|-------------|
| **⟳ Re-evaluate auto-rejected** | After changing rejected keywords — re-runs filter + scoring on all auto-rejected jobs |
| **⟳ Re-score new** | After reviewing many jobs — re-scores with updated preferences without collecting |
| **★ Rank jobs (AI)** | Run only the Voyage + Opus ranking step, without collecting or scoring |
| **💡 Suggest searches** | Claude analyzes your applied jobs and proposes new search query variants |
| **⟳ Fetch missing descriptions** | Appears when some jobs were collected without descriptions — retries them |

---

## Dashboard reference

### Tabs

| Tab | Shows |
|-----|-------|
| **New** | Unreviewed jobs (default) |
| **Reviewed** | Jobs you've read but not decided on |
| **Applied** | Jobs you applied to |
| **Rejected** | Jobs you manually rejected |
| **Auto-rejected** | Jobs auto-rejected by keyword filter |
| **All** | Everything |
| **CV** | Upload and manage your CV |
| **Criteria** | Search queries, locations, keywords |

### Stats bar

| Stat | Meaning |
|------|---------|
| Total / New / Reviewed / Applied / Rejected / Auto-rejected | Job counts by status |
| Avg Score | Average Sonnet score across non-rejected jobs |
| Ranked 📊 | How many jobs have an AI listwise rank; click to open eval report |
| Today / Total | Approximate API spend (Anthropic + Voyage) |

### Job card anatomy

```
┌─────────────────────────────────────────────────────┬────────┐
│ Job Title (link)                                    │  #3    │  ← Opus listwise rank
│ Company · 📍 Location  [source badge]               │  7.4   │  ← Sonnet score
├─────────────────────────────────────────────────────┴────────┤
│ [remote] [senior] [startup] [product] [Python] [Django]      │  ← clickable badges
├──────────────────────────────────────────────────────────────┤
│ AI reasoning: "Strong Python/Django match, product company…" │
│ ▼ Show description                                           │
├──────────────────────────────────────────────────────────────┤
│ [new]  2025-07-01       [Reviewed]  [Applied ✓]  [Reject ✗] │
└──────────────────────────────────────────────────────────────┘
```

---

## Technical deep-dive

### Database schema

All state lives in `data/agent.db` (SQLite). Key tables:

```sql
jobs (
    id               TEXT PRIMARY KEY,    -- hash of url+title+company
    url, title, company, location, source TEXT,
    status           TEXT,                -- new|reviewed|applied|rejected|auto_rejected
    score            REAL,                -- Sonnet 0-10
    score_reason     TEXT,                -- Sonnet explanation
    rejection_reason TEXT,                -- user-written reason
    structured_data  TEXT,               -- JSON from Haiku extractor
    embedding_score  REAL,               -- cosine similarity to ideal vector
    rerank_score     REAL,               -- Voyage cross-encoder score
    listwise_rank    INTEGER,            -- Opus rank (1 = best)
    rank_reason      TEXT,               -- Opus per-job reasoning
    description      TEXT,
    created_at, updated_at DATETIME
)

job_embeddings (
    job_id     TEXT PRIMARY KEY,
    embedding  TEXT,                     -- JSON float array, 1024-dim
    model      TEXT
)

preference_profiles (
    id              INTEGER PRIMARY KEY,
    signals         TEXT,               -- JSON list of ProfileSignal
    applied_count   INTEGER,
    rejected_count  INTEGER,
    created_at      DATETIME
)

usage_log (
    model, module   TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    created_at      DATETIME
)
```

### Pipeline stages in detail

#### 1. Collection

`collector/runner.py` orchestrates all sources. Each source implements `JobSource.search(title, location, days_back, max_results, known_urls)` and returns `RawJob` objects. After collection:

- Jobs are deduplicated by URL (primary) and title+company hash (secondary)
- Existing jobs are skipped; only new ones are inserted with `status='new'`
- New LinkedIn jobs are checked against `rejected` keywords **by title alone** before a description is fetched — a job that's already doomed never costs a page load (`collector/filters.py → title_banned_reason`)
- LinkedIn descriptions are fetched with Playwright, with delays that scale to what's actually happening on the page instead of a flat random range

LinkedIn stealth parameters (`config.py → STEALTH`):
```python
# Search phase — pause after each (title, location) search
search_glance:     5–20 s   flat "glanced at results" component, always applied
search_new:        10–30 s  per newly-found job on that page (0 s added if all duplicates)

# Description phase — one browser session per batch
desc_delay:        8–45 s, scaled to word count (~200 wpm) ± 15% variance
batch_size:        10 descriptions per session
batch_pause:       120–600 s between batches
distract_every_n_batches: 2   # visits a random LinkedIn page (feed/network/jobs) between batches
```

Both delay types keep a 5% chance of an extra 60–300 s pause ("stepped away"), independent of page content.

#### How LinkedIn keyword search actually behaves

This took a lot of live trial and error to pin down — worth reading before changing `title`/`search_query` criteria.

**Every search phrase is wrapped in quotes** (`collector/sources/linkedin.py → search()`): `Senior PHP Developer` becomes `"Senior PHP Developer"` in the `keywords=` URL param. Quotes force LinkedIn to require that **exact phrase as a literal substring** somewhere in the job's searchable text — not "these words in any order" and not a fuzzy/semantic match.

- **Without quotes**, LinkedIn matches loosely on individual words (its own relevance ranking, not a literal filter). This is what searching bare `php` originally did, and it returned Ruby, Java, Salesforce, and Data Engineer postings that had nothing to do with PHP — confirmed by direct testing, which is why quoting was added.
- **Word order matters completely** with quotes, because it's a literal substring match: `"PHP Engineer"` and `"Engineer PHP"` return **completely different, non-overlapping** result sets (verified live — 6 vs 8 results, zero titles in common). Neither is "wrong"; they just catch different real-world title phrasings.
- **A short phrase is a superset of any longer phrase that contains it.** `"PHP Developer"` matches everywhere `"Senior PHP Developer"` would, plus more (`"Lead PHP Developer"`, `"Full Stack PHP Developer"`, bare `"PHP Developer"` with no prefix). This is why the criteria list was consolidated — dropping a redundant longer variant never loses coverage, as long as it's a literal substring of the phrase kept.
- **`"X Software Engineer"` is NOT a superset relationship with `"X Engineer"`** — "Software" sits in between, so these are two different, non-overlapping phrases, not a longer/shorter pair of the same one. Confirmed live: `"Python Software Engineer"` and `"Python Engineer"` returned entirely different job postings. Don't assume any two phrases that "feel similar" are substrings of each other — check literally.

**The best-performing phrase found by testing is the bare quoted language name** — `"PHP"` / `"Python"` alone, no "Developer"/"Engineer" suffix. Verified across Germany, Poland, Denmark, and the US (remote-only + last-24h filters, matching production conditions):
- Never returned zero results, unlike almost every multi-word phrase tried.
- Still clean — sampling 35+ results across two countries found no unrelated (non-PHP, non-IT) postings.
- Catches title patterns no multi-word phrase can, because the word can appear anywhere: `"Senior Backend Engineer, PHP"`, `"Software Engineer – Python"`, `"Backend-Entwickler (Python / PHP)"`.
- Also catches non-English postings, since the token itself isn't translated: German `"PHP-Entwickler"`, `"PHP Softwareentwickler"` all matched a plain `"PHP"` search — a real language-coverage win, since the DACH market posts heavily in German.

Because bare `"PHP"`/`"Python"` is a superset of `"PHP Developer"`, `"PHP Engineer"`, `"PHP Team Lead"`, etc. (all of them literally contain the word), those narrower variants were retired from the `title` criteria. **What's left needs its own entry per framework** (`Symfony Developer`, `Django Developer`, `Laravel Developer`, `FastAPI Developer`, `Flask Developer`) because a framework name doesn't contain the literal word "PHP" or "Python" — bare `"PHP"` won't find a posting titled just `"Symfony Developer"`.

**LinkedIn also supports real Boolean operators** — uppercase `AND` / `OR` / `NOT`, order-independent (`php AND developer` ≡ `developer AND php`, verified live). Tempting, because it directly fixes "0 results" — `php AND developer` returned 500+ hits vs 0–24 for any quoted phrase. **Deliberately not used**: Boolean operators match against the full job description, not just the title, so `php AND developer` also surfaces Java/.NET/generic "Backend Developer" postings where "php" is merely one word buried in a long tech-stack list. Sampled live across 4 countries: roughly half of the top results per search had no PHP/Python connection visible in the title at all. This reintroduces exactly the noise quoting was meant to eliminate, and the existing `required` keyword safety net doesn't help here — `required=[php, python]` can never reject an AND-sourced result, because the search only matched it *because* that word is already present somewhere in the document.

**The "no results" trap this all depends on getting right:** when a quoted phrase matches nothing, LinkedIn doesn't show an empty page — it shows "No matching jobs found" plus an unrelated **"Jobs you may be interested in"** widget (your own personalized recommendations, unrelated to the search). That widget reuses the exact same markup (`.scaffold-layout__list-item`) as real results, so a naive scraper — which is what this one used to be — silently scrapes someone's LinkedIn recommendations and inserts them as if they were real search hits for that query. `_collect_cards()` now checks for `.jobs-search-no-results-banner` and treats its presence as zero results. This is the reason `days_back=1` combined with narrow/compound phrases so often logged identical "found" jobs across unrelated queries and countries before the fix — always double-check this isn't happening again if search result counts look suspiciously identical across different queries.

**The actual reason for frequent "0 new jobs" isn't the phrase, usually — it's `days_back=1` + remote-only (`f_WT=2`) stacked together.** Verified live: `"Python Developer"` in Germany with no date filter has 24 results; the same phrase restricted to the last 24 hours has 0. Multiply that scarcity across every (title, location) combination run daily, and most individual searches will legitimately find nothing new — this is expected, not a bug, given how narrow the freshness window is relative to real posting volume for any single niche+country combination.

#### 2. Preference distillation

`preference_agent/runner.py` — runs with **Claude Opus 4.8**.

Inputs:
- All `applied` jobs (title, company, location, description up to 1500 chars)
- Up to 50 most recent `rejected` jobs with user-written rejection reasons
- Up to 10 divergence cases: jobs ranked ≤ 5 by Opus but rejected by user, or ranked ≥ 16 but applied to (strongest learning signal)

Output — a list of `ProfileSignal` objects:
```
ACCEPT[company_type=product_saas; conf=HIGH; n=3/3]
REJECT[company_type=agency_outsourcing; conf=ABSOLUTE; n=5/5; note="body shop"]
INFER[compensation=min_100_eur_h; from=3 examples]
NEUTRAL[contract_form; no_signal]
```

Confidence levels: `ABSOLUTE > HIGH > MEDIUM > LOW`. `NEUTRAL` signals are stripped before being injected into the scorer.

The distiller skips if `applied_count` and `rejected_count` are unchanged since the last saved profile.

Distillation is triggered as a pipeline step — not on every decision:
- At the start of **Run Agent** (before scoring new jobs)
- At the start of **Re-score new**
- On demand from **Preferences** modal

#### 3. Scoring

`evaluator/scorer.py` — runs with **Claude Sonnet 4.6**, tool-use API (`submit_score`).

Prompt structure:
```
[System]
You are evaluating job listings for a software developer.

[Candidate profile — from CV]
Stack: Python, Django, PostgreSQL, Docker...
Experience: 8 years backend...

[Preference profile — from distillation]
ACCEPT[company_type=product_saas; conf=HIGH]
REJECT[company_type=agency_outsourcing; conf=ABSOLUTE]
...

[Few-shot examples]
APPLIED: "Senior Backend Engineer" @ ProductCo ...
REJECTED: "PHP Dev" @ AgencyXYZ ... [reason: outsourcing body shop]

[Active criteria]
preferred: Symfony, Docker
rejected: "must be based in UK"

[Job to score]
Title: ...
Company: ...
Description: ...
```

Output: `score` (0–10 float) + `reason` (1–2 sentence explanation). Auto-rejection (`status='auto_rejected'`) is applied by the evaluator runner for jobs matching `rejected` criteria, before calling Claude.

#### 4. Structured extraction

`extractor/runner.py` — runs with **Claude Haiku 4.5**, tool-use API (`submit_structured_data`).

Extracts per-job JSON from the description (first 3000 chars):
```json
{
  "remote": true,
  "hybrid": false,
  "seniority": "senior",
  "salary_min": 15000, "salary_max": 20000, "salary_currency": "PLN",
  "stack": ["Python", "Django", "PostgreSQL"],
  "company_type": "startup",
  "product_vs_outsourcing": "product",
  "working_language": "english"
}
```

Fields default to `null` when not explicitly stated — no inference. Stored in `jobs.structured_data` as JSON. Powers the clickable badge filters in the dashboard.

#### 5. Embeddings

`embeddings/indexer.py` + `embeddings/client.py` — **Voyage voyage-3-large**, 1024-dim.

Each job is embedded as: `"{title} at {company}\n{description[:2000]}"` with `input_type="document"`.

The **ideal candidate vector** is computed from your feedback:
```
ideal = centroid(applied_embeddings) − 0.3 × centroid(rejected_embeddings)
```

The 0.3 weight on rejected embeddings pushes the ideal vector away from job types you've rejected without over-correcting. Each new job is scored by cosine similarity to this vector → stored as `embedding_score`.

#### 6. Cross-encoder rerank

`ranker/reranker.py` — **Voyage rerank-2**.

Top-50 jobs by `embedding_score` are passed to the cross-encoder with a query derived from the CV summary and preference signals. The cross-encoder evaluates each (query, document) pair jointly (not independently like an embedding model), giving more accurate relevance scores. Top-20 by `rerank_score` proceed to listwise ranking.

#### 7. Listwise ranking

`ranker/listwise.py` — **Claude Opus 4.8** with extended thinking (`adaptive` mode, `effort=high`).

The top-20 jobs from the reranker are passed together in a single prompt. Opus sees all 20 simultaneously and ranks them relative to each other — not by absolute score. This is the key advantage over pairwise scoring: Opus can reason about trade-offs across the full set.

Output format — JSON in `<ranking>` tags:
```json
[
  {"job_id": "abc123", "reason": "Exact stack match, product company, senior role"},
  {"job_id": "def456", "reason": "Good match but agency, lower confidence"},
  ...
]
```

Each job gets a `listwise_rank` (1 = best) and `rank_reason`. Jobs outside the top-20 are not ranked (NULL).

Extended thinking lets Opus internally reason about candidate-job fit before committing to an ordering. This produces more consistent rankings than a simple prompt.

#### Evaluation metrics

`GET /api/eval/report` returns:

- **Precision@5** and **Precision@10** — of the top-K ranked jobs, what fraction did the user apply to or mark as reviewed? Higher = better ranking.
- **Divergence cases** — jobs where ranking and user decision strongly disagree:
  - `rank ≤ 5` + `status = rejected` → false positive (Opus liked it, you didn't)
  - `rank ≥ 16` + `status = applied` → false negative (Opus missed a good one)

Divergence cases are fed back into the next distillation run as high-priority signals.

### Model usage and approximate costs

| Stage | Model | Cost approx. |
|-------|-------|-------------|
| Distillation | Opus 4.8 | ~$0.40/run (50 jobs × 1500 chars) |
| Scoring | Sonnet 4.6 | ~$0.007/job |
| Extraction | Haiku 4.5 | ~$0.001/job |
| Embedding | Voyage voyage-3-large | $0.06/1M tokens |
| Reranking | Voyage rerank-2 | $0.05/1K queries |
| Listwise rank | Opus 4.8 | ~$0.40/run (top-20 jobs) |

**Distillation runs once per Run Agent / Re-score, not on every decision.** This is the most expensive step; the budget is fixed (~50 jobs in context) regardless of total job count.

### Cost tracking

Every API call logs to `usage_log`. The dashboard stats bar shows today's and total spend. The `MODEL_COSTS` dict in `config.py` holds the rates — update it if pricing changes.

---

## Project structure

```
JobAgent/
├── config.py                       # API keys, models, stealth timings, ranking params
├── collector/
│   ├── base.py                     # JobSource ABC + RawJob dataclass
│   ├── filters.py                  # Title pre-filter (before fetch) + full rejected/required filter (after)
│   ├── runner.py                   # Orchestrates sources → descriptions → DB
│   └── sources/
│       ├── linkedin.py             # Playwright + system Chrome, stealth delays
│       ├── weworkremotely.py       # RSS feed
│       ├── remotive.py             # JSON API
│       ├── remoteok.py             # JSON API
│       └── workingnomads.py        # JSON API
├── evaluator/
│   ├── profile.py                  # Load CV profile from DB
│   ├── scorer.py                   # Sonnet prompt builder + tool-use scoring
│   └── runner.py                   # Score unscored jobs; auto-reject by keywords
├── extractor/
│   └── runner.py                   # Haiku structured extraction per job
├── embeddings/
│   ├── client.py                   # Voyage AI wrapper (embed + rerank + cosine)
│   └── indexer.py                  # Build ideal vector; score by similarity
├── ranker/
│   ├── reranker.py                 # Voyage cross-encoder rerank (top-50 → top-20)
│   └── listwise.py                 # Opus listwise ranking (top-20 → ordered list)
├── preference_agent/
│   ├── profile.py                  # ProfileSignal schema + render_signals()
│   └── runner.py                   # Distill apply/reject history → JSON profile
├── evaluation/
│   └── harness.py                  # Precision@K, divergence cases
├── query_expansion/
│   └── runner.py                   # Suggest new search queries from applied jobs
├── db/
│   ├── connection.py               # SQLite connection factory
│   ├── migrations.py               # Schema init + ALTER TABLE migrations
│   ├── types.py                    # TypedDicts: JobRow, ScoreResult, ProfileSignal
│   └── repositories/
│       ├── job_repository.py       # jobs CRUD, search, feedback, ranking scores
│       ├── criteria_repository.py
│       ├── cv_repository.py
│       ├── preference_repository.py
│       ├── session_repository.py
│       └── usage_repository.py     # API cost tracking
├── scripts/
│   ├── run_all.py                  # CLI: full pipeline
│   ├── rescore_new.py              # Re-score new jobs only
│   ├── distill_preferences.py      # Run distillation once
│   ├── rank_jobs.py                # Run embed + rerank + listwise only
│   ├── extract_jobs.py             # Backfill structured extraction for all jobs
│   ├── index_embeddings.py         # Backfill embeddings for all jobs
│   ├── backfill_descriptions.py    # Retry jobs with missing descriptions
│   └── reevaluate_rejected.py      # Re-run filter + scoring on auto-rejected jobs
├── web/
│   ├── app.py                      # Flask app factory
│   ├── routes/
│   │   ├── jobs.py                 # /api/jobs, /api/stats, status updates
│   │   ├── runner.py               # WebSocket streams for all pipeline actions
│   │   ├── criteria.py
│   │   ├── cv.py
│   │   ├── ranking.py
│   │   ├── query_expansion.py
│   │   └── evaluation.py
│   ├── templates/dashboard.html
│   └── static/
│       ├── dashboard.js
│       └── dashboard.css
├── tests/
│   ├── unit/                       # Logic, prompt builders, parsers
│   ├── integration/                # DB, Flask routes, evaluator runner
│   └── e2e/                        # Real API calls
└── data/                           # gitignored
    ├── agent.db
    ├── chrome_profile/
    └── logs/
```

---

## Running tests

```bash
pytest                  # unit + integration (no API keys needed, all mocked)
pytest tests/unit/
pytest tests/integration/
pytest -m e2e           # real API calls — requires ANTHROPIC_API_KEY
```

Unit and integration tests use in-memory SQLite and mock all external API calls. ~420 tests, ~15–20 seconds.

---

## Troubleshooting

**Agent finds no jobs** — check that you have at least one `search_query` and one `location` in the Criteria tab.

**LinkedIn login required** — on first run, Chrome opens at the login page. Log in manually; your session is saved to `data/chrome_profile/`. If it expires, delete that directory and log in again.

**Scraping breaks / wrong jobs** — LinkedIn occasionally changes its HTML. Update CSS selectors in `collector/sources/linkedin.py`.

**`overloaded` from Anthropic** — the evaluator retries automatically (3×, 30 s / 60 s). If it keeps failing, wait and retry.

**Dashboard shows "Running" with nothing running** — a session was left in `status='running'` after a crash. Either wait 6 hours (auto-clears) or:
```sql
UPDATE sessions SET status='error' WHERE status='running';
```

**Jobs missing descriptions** — click **⟳ Fetch missing descriptions** in the toolbar.

**Ranking badges not showing** — structured extraction (`extract_jobs.py`) hasn't run yet. After adding Anthropic credits, run:
```bash
python scripts/extract_jobs.py
```

**Voyage rate limit errors** — the free tier allows 3 RPM. Add a payment method on [dashboard.voyageai.com](https://dashboard.voyageai.com) to unlock 600 RPM. Then update `BATCH_SIZE=128` and `BATCH_DELAY=1` in `embeddings/indexer.py`.

**Score not changing after re-score** — the distiller skips if `applied_count` and `rejected_count` haven't changed since the last run. Mark at least one job as applied or rejected first.
