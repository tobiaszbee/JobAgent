# JobAgent — Rebuild Plan

## Context and Decisions

### What and why
The original project works but is monolithic. Decision: rebuild from scratch (new DB, new structure) in 4 phases.

### Key design decisions
- **Clean start** — new SQLite database, no migration from the old `data/agent.db`
- **JobSource abstraction** — each job source (LinkedIn, others) is a separate class implementing a common interface; independent modules
- **CV from DB** — candidate profile is not hardcoded; user uploads a PDF via UI, backend parses it and saves to DB; evaluator reads from DB
- **Learning via UI** — marking jobs as "applied" / "rejected" in the dashboard saves to DB and feeds into Claude's few-shot examples
- **Phase 3 (embeddings) after Phase 4** — automation is simpler than embeddings, no reason to delay it

### Current state (before rebuild)
- `src/agent.py` — main loop: scrape → insert → evaluate
- `src/browser.py` — Playwright + Chrome, LinkedIn login, scraping
- `src/evaluator.py` — Claude prompt, hardcoded candidate profile (~line 98)
- `src/db/` — connection, migrations, repositories
- `src/web/app.py` — Flask dashboard + WebSocket runner
- `src/seed_criteria.py` — **BROKEN**: imports `JOB_CRITERIA` from `config.py` which doesn't exist there
- `config.py` — API key, model name, paths

---

## Target project structure

```
JobAgent/
  collector/
    __init__.py
    base.py              # JobSource (abstract), RawJob (dataclass)
    filters.py           # keyword exclusion filtering (no AI)
    runner.py            # orchestration: fetch → filter → save to DB
    sources/
      __init__.py
      linkedin.py        # first JobSource implementation

  evaluator/
    __init__.py
    profile.py           # loads active CV profile from DB
    scorer.py            # Claude scoring (prompt + retry logic)
    embeddings.py        # embedding generation and similarity search (Phase 3)
    runner.py            # orchestration: score everything with status=new

  web/
    __init__.py
    app.py
    routes/
      __init__.py
      jobs.py            # job list, status changes
      criteria.py        # criteria management
      cv.py              # CV upload, profile preview (Phase 2)
      runner.py          # trigger collector/evaluator from UI
    static/
      dashboard.css
      dashboard.js
    templates/
      dashboard.html

  db/
    __init__.py
    connection.py
    migrations.py
    repositories/
      __init__.py
      job_repository.py
      criteria_repository.py
      cv_repository.py       # new (Phase 2)
      session_repository.py

  scripts/
    collect.py           # CLI: scrape + filter + save only (Phase 4)
    evaluate.py          # CLI: score new jobs only (Phase 4)

  config.py
  requirements.txt
  .env
  .env.example
  .gitignore
```

---

## New DB schema

```sql
-- Main jobs table (extended with source and source_id)
CREATE TABLE jobs (
    id           TEXT PRIMARY KEY,           -- URL hash or source_id
    title        TEXT NOT NULL,
    company      TEXT,
    location     TEXT,
    url          TEXT UNIQUE,
    description  TEXT,
    source       TEXT DEFAULT 'linkedin',    -- NEW: where the job came from
    source_id    TEXT,                       -- NEW: job ID at the source
    status       TEXT DEFAULT 'new',         -- new | reviewed | applied | rejected | auto_rejected
    score        REAL,
    score_reason TEXT,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Search and evaluation criteria
CREATE TABLE criteria (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,               -- title | location | required | preferred | rejected
    value      TEXT NOT NULL,
    is_active  INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Agent run sessions
CREATE TABLE sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,
    jobs_found  INTEGER DEFAULT 0,
    jobs_scored INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'running'      -- running | done | error
);

-- Candidate profiles parsed from CV (Phase 2)
CREATE TABLE cv_profiles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    filename   TEXT,
    raw_text   TEXT,                        -- text extracted from PDF
    parsed     TEXT,                        -- JSON: stack, years, preferences, location
    is_active  INTEGER DEFAULT 1,           -- only one active at a time
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Job embeddings (Phase 3)
CREATE TABLE job_embeddings (
    job_id     TEXT PRIMARY KEY REFERENCES jobs(id),
    embedding  TEXT,                        -- JSON float array
    model      TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Key interfaces

### JobSource (collector/base.py)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class RawJob:
    title: str
    company: str
    location: str
    url: str
    source: str           # e.g. "linkedin"
    source_id: str | None = None
    description: str | None = None

class JobSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def search(self, title: str, location: str, days_back: int) -> list[RawJob]: ...
```

Adding a new source = new class in `sources/` implementing `JobSource`, nothing else to touch.

### CV Profile (evaluator/profile.py)

```python
# Loads the active profile from DB and returns it as a dict.
# Raises ValueError with a clear message if no active profile exists.
def load_active_profile(db) -> dict:
    ...
# dict fields: stack, years_experience, location, remote_preference, seniority, raw_summary
```

---

## Phases and iterations

---

### Phase 1 — Foundation: new structure + JobSource

**Goal:** project works the same as before (scrape → score → dashboard), but in the new architecture.

---

#### Iteration 1.1 — New DB schema and repositories

Files to create:
- `db/connection.py` — same logic, just path to the new `data/agent.db`
- `db/migrations.py` — new schema (see above), `CREATE TABLE IF NOT EXISTS`
- `db/repositories/job_repository.py` — methods: `insert`, `get_new`, `get_by_status`, `update_status`, `update_score`
- `db/repositories/criteria_repository.py` — methods: `get_active`, `add`, `toggle`, `delete`
- `db/repositories/session_repository.py` — methods: `start`, `finish`, `update_counts`

Verification: `python -c "from db.migrations import init_db; init_db()"` creates the file without errors.

---

#### Iteration 1.2 — collector/ with JobSource abstraction

Files to create:
- `collector/base.py` — `RawJob` dataclass + `JobSource` ABC (see above)
- `collector/sources/linkedin.py` — refactored `src/browser.py`; class `LinkedInSource(JobSource)`; `search()` returns `list[RawJob]`
- `collector/filters.py` — `def apply_filters(jobs: list[RawJob], rejected_keywords: list[str]) -> list[RawJob]`; no AI, pure string matching
- `collector/runner.py` — `def run(days_back, max_jobs, titles, locations)`: fetch criteria from DB → for each title×location call `source.search()` → `apply_filters()` → deduplicate → save to DB

Notes:
- LinkedIn uses `channel="chrome"` (system Chrome, not Playwright's bundled Chromium) — do NOT run `playwright install`
- Chrome profile saved in `data/chrome_profile/` — first run opens LinkedIn login, user logs in manually; session is reused after that

Verification: `python collector/runner.py --days 1 --max-jobs 5` inserts jobs into DB.

---

#### Iteration 1.3 — evaluator/ (with hardcoded profile for now)

Files to create:
- `evaluator/scorer.py` — refactored `src/evaluator.py`; function `score_job(job, profile_text, criteria, examples) -> (score, reason)`; retry logic (3 attempts, 30s/60s wait on `overloaded`)
- `evaluator/runner.py` — `def run()`: fetch all `status=new` from DB → fetch criteria → fetch examples (applied/rejected) → score each → update DB

Candidate profile: temporarily a hardcoded string in `evaluator/scorer.py` (replaced in Phase 2). Adjust it to your own stack before running.

Verification: after `collector/runner.py` → `evaluator/runner.py`, jobs have a score and reason.

---

#### Iteration 1.4 — web/ and integration + delete src/

Files to create/adapt:
- `web/app.py` — Flask init, blueprint registration
- `web/routes/jobs.py` — `GET /`, `POST /jobs/<id>/status`
- `web/routes/criteria.py` — `GET/POST /criteria`, `DELETE /criteria/<id>`, `POST /criteria/<id>/toggle`
- `web/routes/runner.py` — `POST /run` (triggers collector + evaluator via WebSocket), `GET /run/status`
- Dashboard HTML/CSS/JS — rewritten or adapted from the original

Verification: `python web/app.py` → `http://localhost:5000` → dashboard shows jobs, status changes work, agent can be triggered.

Once verified, delete the entire `src/` directory — everything it contained has been replaced by this point.

---

### Phase 2 — CV as the candidate profile source

**Goal:** no more hardcoded profile; user uploads a PDF via UI.

---

#### Iteration 2.1 — CV upload and parsing

Files to create:
- `db/repositories/cv_repository.py` — `insert(filename, raw_text, parsed_json)`, `get_active() -> dict | None`, `set_active(id)`, `list_all()`
- `web/routes/cv.py` — `POST /cv/upload`: receive PDF → extract text (PyPDF2) → send to Claude with prompt "extract structure: stack, years, location, preferences" → save to DB
- UI: "CV" tab in dashboard with upload form and parsed profile JSON preview

`parsed` JSON format stored in DB:
```json
{
  "stack": ["PHP 8", "Symfony", "MySQL"],
  "years_experience": 8,
  "location": "Poland",
  "remote_preference": "fully remote",
  "seniority": "Senior",
  "raw_summary": "Senior PHP Engineer..."
}
```

Verification: upload PDF → parsed profile visible in UI.

---

#### Iteration 2.2 — Evaluator reads profile from DB

Files to change:
- `evaluator/profile.py` — `load_active_profile(db) -> dict`; raises `ValueError` if no active CV
- `evaluator/scorer.py` — `score_job()` accepts `profile: dict` instead of `profile_text: str`; builds prompt from `parsed` JSON fields
- `evaluator/runner.py` — before scoring: `profile = load_active_profile(db)`; on error → log and abort with clear message

Verification: scoring works with zero hardcoded profile in the codebase.

---

#### Iteration 2.3 — Learning from application history

Files to change:
- `db/repositories/job_repository.py` — `get_examples(limit_positive=8, limit_negative=5) -> (list[Job], list[Job])`: returns jobs with `status='applied'` and `status='rejected'`
- `evaluator/runner.py` — `examples = get_examples(db)` → pass to `scorer.py`
- `evaluator/scorer.py` — few-shot section in prompt: positive (applied) and negative (rejected) examples

Note: `auto_rejected` jobs are NOT used as few-shot — that's machine rejection, not a personal preference signal.

Verification: after a few cycles, scoring improves for similar jobs.

---

### Phase 3 — Embeddings and smarter example selection

**Goal:** few-shot example selection based on semantic similarity, not random.

---

#### Iteration 3.1 — Embedding generation

Files to create:
- `evaluator/embeddings.py` — `generate_embedding(text: str) -> list[float]` (Claude or another model); `save_embedding(db, job_id, embedding, model)`
- `evaluator/runner.py` — after scoring: `generate_embedding(job.description)` → save to `job_embeddings`

---

#### Iteration 3.2 — Similarity search for few-shot

Files to change:
- `evaluator/embeddings.py` — `find_similar(db, query_embedding, status_filter, n=5) -> list[str]` (returns job_ids)
- `evaluator/runner.py` — replace `get_examples(db)` with `find_similar(db, job_embedding, 'applied')` + `find_similar(db, job_embedding, 'rejected')`

---

### Phase 4 — Automation

**Goal:** collector and evaluator run as independent CLI scripts, schedulable via cron.

---

#### Iteration 4.1 — CLI scripts

Files to create:
- `scripts/collect.py` — `python scripts/collect.py --days 7 --max-jobs 50`; uses `collector/runner.py`; logs to stdout
- `scripts/evaluate.py` — `python scripts/evaluate.py`; uses `evaluator/runner.py`; logs to stdout

Both scripts must work independently of each other and independently of `web/`.

---

#### Iteration 4.2 — Scheduler (Windows)

Option A — Windows Task Scheduler:
```powershell
# Run daily at 08:00
schtasks /create /tn "JobAgent-Collect" /tr "python C:\...\scripts\collect.py" /sc daily /st 08:00
schtasks /create /tn "JobAgent-Evaluate" /tr "python C:\...\scripts\evaluate.py" /sc daily /st 08:05
```

Option B — simple `scripts/run_all.py` wrapper triggered manually or by scheduler.

---

## Execution order

```
Phase 1 (1.1 → 1.2 → 1.3 → 1.4)
  ↓
Phase 2 (2.1 → 2.2 → 2.3)
  ↓
Phase 4 (4.1 → 4.2)        ← simpler than Phase 3, don't wait
  ↓
Phase 3 (3.1 → 3.2)        ← once you have enough application history
```

---

## Technical notes

- **Playwright + Chrome**: project uses `channel="chrome"` — drives system Chrome, do NOT run `playwright install`
- **PyPDF2**: for PDF text extraction (already in `requirements.txt`)
- **WebSocket**: `flask-sock` for streaming agent logs to UI (already in project)
- **API key**: only in `.env` as `ANTHROPIC_API_KEY`, never hardcoded
- **Model**: `claude-sonnet-4-6` (set in `config.py`)
- **Retry logic**: 3 attempts on `overloaded`, wait 30s / 60s between retries

---

## Current status

- [x] Phase 1.1 — new DB schema and repositories
- [x] Phase 1.2 — collector + JobSource abstraction
- [x] Phase 1.3 — evaluator (hardcoded profile)
- [x] Phase 1.4 — web + integration
- [ ] Phase 2.1 — CV upload and parsing
- [ ] Phase 2.2 — evaluator reads profile from DB
- [ ] Phase 2.3 — few-shot from application history
- [ ] Phase 4.1 — CLI scripts
- [ ] Phase 4.2 — scheduler
- [ ] Phase 3.1 — embeddings
- [ ] Phase 3.2 — similarity search
