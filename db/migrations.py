from config import DB_BACKEND
from db.connection import get_connection

# One canonical schema shape shared by both backends — {PK} and {TS} are the only
# two places SQLite and Postgres syntax actually diverge (autoincrement id, and the
# datetime column type). Every other statement (TEXT PRIMARY KEY, REFERENCES ... ON
# DELETE CASCADE, UNIQUE, CREATE INDEX IF NOT EXISTS, INTEGER-as-boolean) is valid,
# identical SQL on both engines — keeping one template avoids the two schemas
# silently drifting apart as columns get added over time.
_SCHEMA_TEMPLATE = """
    CREATE TABLE IF NOT EXISTS jobs (
        id               TEXT PRIMARY KEY,
        title            TEXT NOT NULL,
        company          TEXT,
        location         TEXT,
        url              TEXT UNIQUE,
        description      TEXT,
        source           TEXT DEFAULT 'linkedin',
        source_id        TEXT,
        status           TEXT DEFAULT 'new',
        score            REAL,
        score_reason     TEXT,
        rejection_reason TEXT,
        created_at       {TS} DEFAULT CURRENT_TIMESTAMP,
        updated_at       {TS} DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS criteria (
        id         {PK},
        type       TEXT NOT NULL,
        value      TEXT NOT NULL,
        is_active  INTEGER DEFAULT 1,
        created_at {TS} DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(type, value)
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id          {PK},
        started_at  {TS} DEFAULT CURRENT_TIMESTAMP,
        finished_at {TS},
        jobs_found  INTEGER DEFAULT 0,
        jobs_scored INTEGER DEFAULT 0,
        status      TEXT DEFAULT 'running'
    );

    CREATE TABLE IF NOT EXISTS cv_profiles (
        id         {PK},
        filename   TEXT,
        raw_text   TEXT,
        parsed     TEXT,
        is_active  INTEGER DEFAULT 1,
        created_at {TS} DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS job_embeddings (
        job_id     TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        embedding  TEXT,
        model      TEXT,
        created_at {TS} DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS preference_profiles (
        id             {PK},
        content        TEXT NOT NULL,
        applied_count  INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        updated_at     {TS} DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS usage_log (
        id            {PK},
        created_at    {TS} DEFAULT CURRENT_TIMESTAMP,
        model         TEXT NOT NULL,
        module        TEXT NOT NULL,
        input_tokens  INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cost_usd      REAL DEFAULT 0.0
    );

    -- One row per pipeline run (Run Agent, Re-score, Re-evaluate, Rank, Backfill),
    -- snapshotting that run's cost/token breakdown and how many jobs it actually
    -- scored. Deliberately independent of the `jobs` table — deleting jobs must
    -- never change historical cost figures. "cost per 100 jobs" is computed as a
    -- rolling average over these frozen snapshots (see usage_repository.get_summary()),
    -- never as total_cost_usd / COUNT(*) FROM jobs, which silently breaks the moment
    -- any job is deleted (jobs_evaluated shrinks but total_cost_usd doesn't).
    CREATE TABLE IF NOT EXISTS cost_summaries (
        id               {PK},
        run_label        TEXT NOT NULL,        -- 'run_agent' | 'rescore_new' | 'reevaluate_rejected' | 'rank' | 'backfill'
        started_at       {TS} NOT NULL,
        finished_at      {TS} DEFAULT CURRENT_TIMESTAMP,
        jobs_evaluated   INTEGER DEFAULT 0,     -- count of scorer-module API calls in this run
        total_cost_usd   REAL DEFAULT 0.0,
        cost_per_100_usd REAL,                  -- NULL when jobs_evaluated = 0 (nothing to rate)
        breakdown        TEXT NOT NULL          -- JSON: {{model: {{input_tokens, output_tokens, cost_usd}}}}
    );

    -- Per-search outcome log: one row per (search_query, location) search call.
    -- Not yet used to drive any decision — a data foundation for a future
    -- "suggest excluding this query, it never finds anything" feature.
    CREATE TABLE IF NOT EXISTS search_stats (
        id           {PK},
        session_id   INTEGER REFERENCES sessions(id),
        source       TEXT NOT NULL,
        search_query TEXT NOT NULL,
        location     TEXT NOT NULL,
        cards_found  INTEGER DEFAULT 0,
        new_found    INTEGER DEFAULT 0,
        searched_at  {TS} DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_search_stats_query ON search_stats(source, search_query);

    -- Search queries auto-excluded (currently: LinkedIn only) after proving to
    -- have a very high reject rate with zero positive yield, or to consistently
    -- surface nothing new — see scripts/prune_search_queries.py. Criteria rows
    -- stay untouched/active; collector/runner.py filters this table separately
    -- so exclusion is source-scoped and trivially reversible (DELETE the row).
    CREATE TABLE IF NOT EXISTS excluded_search_queries (
        id           {PK},
        source       TEXT NOT NULL,
        search_query TEXT NOT NULL,
        reason       TEXT NOT NULL,
        excluded_at  {TS} DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source, search_query)
    );

    -- Candidate-stated preferences from the post-CV-upload questionnaire — ground
    -- truth from the candidate, distinct from cv_profiles.parsed (inferred from CV
    -- text) and from criteria (collector search-dimension config, not candidate
    -- filtering preferences). List-valued fields are stored as JSON text, matching
    -- the convention already used by jobs.structured_data and cv_profiles.parsed.
    -- Every field is optional — the questionnaire has no required questions.
    CREATE TABLE IF NOT EXISTS candidate_preferences (
        id                       {PK},
        cv_profile_id            INTEGER REFERENCES cv_profiles(id),
        work_mode                TEXT,     -- JSON array: ["remote","hybrid","onsite"]
        remote_countries         TEXT,     -- JSON array of ISO country codes
        hybrid_cities            TEXT,     -- JSON array of free-text city names
        salary_min               INTEGER,
        salary_max               INTEGER,
        salary_currency          TEXT,     -- PLN | EUR | USD | GBP
        show_jobs_without_salary INTEGER DEFAULT 1,
        seniority_levels         TEXT,     -- JSON array: ["senior","lead"]
        role_types               TEXT,     -- JSON array: ["developer","devops"]
        preferred_company_types  TEXT,     -- JSON array
        excluded_company_types   TEXT,     -- JSON array — hard constraint
        preferred_industries     TEXT,     -- JSON array
        excluded_industries      TEXT,     -- JSON array — hard constraint
        extra_tech               TEXT,     -- JSON array, added on top of CV-derived stack
        avoided_tech             TEXT,     -- JSON array
        languages                TEXT,     -- JSON array: [{{"language":"english","level":"C1"}}]
        open_notes               TEXT,     -- free text, future embedding input
        is_active                INTEGER DEFAULT 1,
        created_at               {TS} DEFAULT CURRENT_TIMESTAMP
    );

    -- User calling out a specific pro/con from a job's score_breakdown as not
    -- applicable to them (e.g. "timezone isn't an issue for me"), with a required
    -- reason. Never changes the score of the job it came from — it's a one-way
    -- feed into preference_agent/runner.py's distillation prompt so future scoring
    -- learns the pattern. See preference_agent/runner.py::_build_dismissed_section().
    CREATE TABLE IF NOT EXISTS dismissed_score_items (
        id          {PK},
        job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        item_type   TEXT NOT NULL,     -- 'pro' | 'con'
        item_text   TEXT NOT NULL,
        reason      TEXT NOT NULL,
        created_at  {TS} DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_dismissed_score_items_job ON dismissed_score_items(job_id);
"""

# (table, column, sqlite_type_sql) — sqlite_type_sql is applied verbatim for the
# SQLite path (idempotency via _column_exists); the Postgres path derives the same
# column/type pair automatically via ADD COLUMN IF NOT EXISTS, so one list drives both.
_NEW_COLUMNS = [
    ("jobs", "rejection_reason",  "TEXT"),
    ("sessions", "jobs_scored",   "INTEGER DEFAULT 0"),
    ("preference_profiles", "content_format", "TEXT DEFAULT 'text'"),
    ("jobs", "structured_data",   "TEXT"),
    ("jobs", "embedding_score",   "REAL"),
    ("jobs", "rerank_score",      "REAL"),
    ("jobs", "listwise_rank",     "INTEGER"),
    ("jobs", "rank_reason",       "TEXT"),
    ("jobs", "score_breakdown",   "TEXT"),
    ("jobs", "debate_flag",       "TEXT"),
    ("jobs", "debate_note",       "TEXT"),
    ("preference_profiles", "dismissed_count", "INTEGER DEFAULT 0"),
    ("jobs", "search_query",  "TEXT"),
    ("jobs", "would_apply",        "INTEGER"),
    ("jobs", "would_apply_reason", "TEXT"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _has_cascade_delete(conn, table: str) -> bool:
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return any(row["on_delete"] == "CASCADE" for row in rows)


def _add_cascade_delete_to_job_refs(conn) -> None:
    """SQLite-only: job_embeddings and dismissed_score_items originally referenced
    jobs(id) without ON DELETE CASCADE, so deleting any job that had an embedding or
    a dismissed pro/con failed with a FOREIGN KEY constraint error. SQLite can't
    ALTER a FK's ON DELETE action in place — this is the standard rebuild-and-swap
    fix, run once per DB. Per SQLite's documented procedure for this kind of schema
    surgery, foreign key enforcement is switched off for the duration (it must not
    be toggled inside a transaction, hence the commit() before and after). Not
    needed on Postgres — the schema template above already has the cascade inline,
    so a fresh Postgres DB is correct from creation."""
    needs_embeddings_fix = not _has_cascade_delete(conn, "job_embeddings")
    needs_dismissed_fix = not _has_cascade_delete(conn, "dismissed_score_items")
    if not (needs_embeddings_fix or needs_dismissed_fix):
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")

    if needs_embeddings_fix:
        conn.executescript("""
            ALTER TABLE job_embeddings RENAME TO job_embeddings_old;
            CREATE TABLE job_embeddings (
                job_id     TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                embedding  TEXT,
                model      TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO job_embeddings SELECT * FROM job_embeddings_old WHERE job_id IN (SELECT id FROM jobs);
            DROP TABLE job_embeddings_old;
        """)

    if needs_dismissed_fix:
        conn.executescript("""
            ALTER TABLE dismissed_score_items RENAME TO dismissed_score_items_old;
            CREATE TABLE dismissed_score_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                item_type   TEXT NOT NULL,
                item_text   TEXT NOT NULL,
                reason      TEXT NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO dismissed_score_items (id, job_id, item_type, item_text, reason, created_at)
                SELECT id, job_id, item_type, item_text, reason, created_at
                FROM dismissed_score_items_old WHERE job_id IN (SELECT id FROM jobs);
            DROP TABLE dismissed_score_items_old;
            CREATE INDEX IF NOT EXISTS idx_dismissed_score_items_job ON dismissed_score_items(job_id);
        """)

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _init_sqlite(conn) -> None:
    conn.executescript(_SCHEMA_TEMPLATE.format(PK="INTEGER PRIMARY KEY AUTOINCREMENT", TS="DATETIME"))
    conn.commit()

    for table, column, type_sql in _NEW_COLUMNS:
        if not _column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}")
            conn.commit()

    _add_cascade_delete_to_job_refs(conn)


def _init_postgres(conn) -> None:
    conn.executescript(_SCHEMA_TEMPLATE.format(PK="INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY", TS="TIMESTAMP"))
    conn.commit()

    # Postgres supports ADD COLUMN IF NOT EXISTS natively (9.6+) — no PRAGMA-style
    # existence check needed, every entry just runs unconditionally and idempotently.
    for table, column, type_sql in _NEW_COLUMNS:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {type_sql}")
        conn.commit()

    # No _add_cascade_delete_to_job_refs call: the schema template above already
    # has ON DELETE CASCADE inline, so a fresh Postgres DB never has the bug it fixes.


def init_db() -> None:
    conn = get_connection()
    if DB_BACKEND == "postgres":
        _init_postgres(conn)
    else:
        _init_sqlite(conn)
    conn.close()
