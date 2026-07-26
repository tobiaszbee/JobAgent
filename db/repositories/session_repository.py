from db.connection import get_connection
from config import DB_BACKEND


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


def cancel_active() -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE sessions SET status='cancelled', finished_at=CURRENT_TIMESTAMP
           WHERE status='running'"""
    )
    conn.commit()
    conn.close()


def has_active_run() -> bool:
    """True if a session started within the last 6 hours is still running."""
    conn = get_connection()
    recency_clause = ("started_at > NOW() - INTERVAL '6 hours'" if DB_BACKEND == "postgres"
                       else "started_at > datetime('now', '-6 hours')")
    row = conn.execute(
        f"SELECT id FROM sessions WHERE status = 'running' AND {recency_clause}"
    ).fetchone()
    conn.close()
    return row is not None


def get_last_finished_at() -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT finished_at FROM sessions WHERE status = 'done' ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["finished_at"] if row else None


def get_latest() -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None
