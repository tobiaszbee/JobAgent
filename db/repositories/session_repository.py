from db.connection import get_connection


def start() -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO sessions (status) VALUES ('running')"
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id


def finish(session_id: int, jobs_found: int, jobs_scored: int, status: str = "done") -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE sessions
           SET finished_at = CURRENT_TIMESTAMP, jobs_found = ?, jobs_scored = ?, status = ?
           WHERE id = ?""",
        (jobs_found, jobs_scored, status, session_id)
    )
    conn.commit()
    conn.close()


def has_active_run() -> bool:
    """True if a session started within the last 6 hours is still running."""
    conn = get_connection()
    row = conn.execute(
        """SELECT id FROM sessions WHERE status = 'running'
           AND started_at > datetime('now', '-6 hours')"""
    ).fetchone()
    conn.close()
    return row is not None


def get_latest() -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None
