from src.db.connection import get_connection


def insert(job_id, notes=None):
    # also syncs job to examples table for few-shot learning; caller updates job status separately
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO applications (job_id, notes) VALUES (?, ?)",
        (job_id, notes)
    )
    job = conn.execute(
        "SELECT url, title, company, description FROM jobs WHERE id = ?",
        (job_id,)
    ).fetchone()
    if job:
        conn.execute(
            "INSERT OR IGNORE INTO examples (url, title, company, description) VALUES (?, ?, ?, ?)",
            (job["url"], job["title"], job["company"], job["description"] or "")
        )
    conn.commit()
    conn.close()


def get_all():
    conn = get_connection()
    rows = conn.execute(
        "SELECT a.*, j.title, j.company FROM applications a JOIN jobs j ON a.job_id = j.id ORDER BY a.applied_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_status(application_id, status):
    conn = get_connection()
    conn.execute("UPDATE applications SET status = ? WHERE id = ?", (status, application_id))
    conn.commit()
    conn.close()
