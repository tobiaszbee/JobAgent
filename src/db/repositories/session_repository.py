from src.db.connection import get_connection


def start():
    conn = get_connection()
    cursor = conn.execute("INSERT INTO sessions DEFAULT VALUES")
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id


def finish(session_id, jobs_found, jobs_new, jobs_scored, status="completed"):
    conn = get_connection()
    conn.execute(
        """UPDATE sessions
           SET finished_at = CURRENT_TIMESTAMP,
               jobs_found = ?, jobs_new = ?, jobs_scored = ?, status = ?
           WHERE id = ?""",
        (jobs_found, jobs_new, jobs_scored, status, session_id)
    )
    conn.commit()
    conn.close()