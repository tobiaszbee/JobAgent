from src.db.connection import get_connection


def run():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            company     TEXT,
            location    TEXT,
            url         TEXT UNIQUE,
            description TEXT,
            score       REAL,
            reasoning   TEXT,
            status      TEXT DEFAULT 'new',
            found_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS applications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id      TEXT NOT NULL REFERENCES jobs(id),
            applied_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            status      TEXT DEFAULT 'sent',
            notes       TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME,
            jobs_found  INTEGER DEFAULT 0,
            jobs_new    INTEGER DEFAULT 0,
            jobs_scored INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS examples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT UNIQUE,
            title       TEXT,
            company     TEXT,
            description TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS criteria (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            type     TEXT NOT NULL,
            value    TEXT NOT NULL,
            active   INTEGER DEFAULT 1,
            UNIQUE(type, value)
        );
    """)
    conn.commit()
    conn.close()