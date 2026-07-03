from db.connection import get_connection


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def init_db() -> None:
    conn = get_connection()
    conn.executescript("""
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
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS criteria (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            type       TEXT NOT NULL,
            value      TEXT NOT NULL,
            is_active  INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(type, value)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME,
            jobs_found  INTEGER DEFAULT 0,
            jobs_scored INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS cv_profiles (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            filename   TEXT,
            raw_text   TEXT,
            parsed     TEXT,
            is_active  INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS job_embeddings (
            job_id     TEXT PRIMARY KEY REFERENCES jobs(id),
            embedding  TEXT,
            model      TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS preference_profiles (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            content        TEXT NOT NULL,
            applied_count  INTEGER DEFAULT 0,
            rejected_count INTEGER DEFAULT 0,
            updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    for table, column, sql in [
        ("jobs", "rejection_reason", "ALTER TABLE jobs ADD COLUMN rejection_reason TEXT"),
        ("sessions", "jobs_scored", "ALTER TABLE sessions ADD COLUMN jobs_scored INTEGER DEFAULT 0"),
    ]:
        if not _column_exists(conn, table, column):
            conn.execute(sql)
            conn.commit()

    # Seed default criteria (INSERT OR IGNORE — safe to re-run on existing DBs)
    _DEFAULT_CRITERIA = [
        ("required", "PHP mentioned in the job description — NOTE: Laravel, Symfony, WordPress are PHP frameworks, so they count as PHP"),
        ("required", "Remote work possible"),
        ("rejected", "Candidate must physically relocate or be resident in a specific country"),
        ("rejected", "Role is on-site with NO remote option"),
        ("rejected", "Role is junior or intern level"),
        ("rejected", "Job listing is not in English"),
        ("rejected", '"Remote, UK based" or "UK based, remote" — means candidate must be in UK'),
        ("rejected", '"Remote within UK" or "UK remote only" — means candidate must be in UK'),
        ("rejected", '"Must be eligible to work in the UK" — means physical presence in UK required'),
    ]
    for type_, value in _DEFAULT_CRITERIA:
        conn.execute(
            "INSERT OR IGNORE INTO criteria (type, value) VALUES (?, ?)",
            (type_, value),
        )
    conn.commit()

    conn.close()
