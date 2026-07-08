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

        CREATE TABLE IF NOT EXISTS usage_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            model         TEXT NOT NULL,
            module        TEXT NOT NULL,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd      REAL DEFAULT 0.0
        );
    """)
    conn.commit()

    for table, column, sql in [
        ("jobs", "rejection_reason",  "ALTER TABLE jobs ADD COLUMN rejection_reason TEXT"),
        ("sessions", "jobs_scored",   "ALTER TABLE sessions ADD COLUMN jobs_scored INTEGER DEFAULT 0"),
        ("preference_profiles", "content_format", "ALTER TABLE preference_profiles ADD COLUMN content_format TEXT DEFAULT 'text'"),
        ("jobs", "structured_data",   "ALTER TABLE jobs ADD COLUMN structured_data TEXT"),
        ("jobs", "embedding_score",   "ALTER TABLE jobs ADD COLUMN embedding_score REAL"),
        ("jobs", "rerank_score",      "ALTER TABLE jobs ADD COLUMN rerank_score REAL"),
        ("jobs", "listwise_rank",     "ALTER TABLE jobs ADD COLUMN listwise_rank INTEGER"),
        ("jobs", "rank_reason",       "ALTER TABLE jobs ADD COLUMN rank_reason TEXT"),
    ]:
        if not _column_exists(conn, table, column):
            conn.execute(sql)
            conn.commit()

    conn.close()
