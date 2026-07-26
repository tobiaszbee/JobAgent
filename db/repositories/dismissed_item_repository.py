from db.connection import get_connection


def insert(job_id: str, item_type: str, item_text: str, reason: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO dismissed_score_items (job_id, item_type, item_text, reason) VALUES (?, ?, ?, ?)",
        (job_id, item_type, item_text, reason),
    )
    conn.commit()
    conn.close()


def get_for_job(job_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT item_type, item_text, reason, created_at FROM dismissed_score_items "
        "WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent(limit: int = 50) -> list[dict]:
    """Most recent dismissals across all jobs, for the distillation prompt."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT d.item_type, d.item_text, d.reason, d.created_at, j.title, j.company
           FROM dismissed_score_items d JOIN jobs j ON j.id = d.job_id
           ORDER BY d.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_all() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM dismissed_score_items").fetchone()[0]
    conn.close()
    return n
