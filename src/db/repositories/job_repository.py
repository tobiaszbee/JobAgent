import hashlib
from src.db.connection import get_connection


def generate_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:16]


def exists(url):
    conn = get_connection()
    row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row is not None


def exists_by_title_company(title, company):
    # prevents duplicate listings for the same role posted in multiple locations
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM jobs WHERE LOWER(title) = LOWER(?) AND LOWER(company) = LOWER(?)",
        (title.strip(), company.strip())
    ).fetchone()
    conn.close()
    return row is not None


def insert(title, company, location, url, description):
    if exists(url):
        return None
    if exists_by_title_company(title, company):
        return None
    job_id = generate_id(url)
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, url, description) VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, title, company, location, url, description)
    )
    conn.commit()
    conn.close()
    return job_id


def update_description(job_id, description):
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (description, job_id)
    )
    conn.commit()
    conn.close()


def update_score(job_id, score, reasoning):
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET score = ?, reasoning = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (score, reasoning, job_id)
    )
    conn.commit()
    conn.close()


def update_status(job_id, status):
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, job_id)
    )
    conn.commit()
    conn.close()


def get_pending_evaluation():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' ORDER BY found_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_top(min_score=6.0, limit=20):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE score >= ? AND status != 'rejected' ORDER BY score DESC LIMIT ?",
        (min_score, limit)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def search(status=None, min_score=None, query=None):
    conn = get_connection()
    sql = "SELECT * FROM jobs WHERE 1=1"
    params = []

    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)

    if min_score is not None:
        sql += " AND (score >= ? OR score IS NULL)"
        params.append(min_score)

    if query:
        sql += " AND (title LIKE ? OR company LIKE ? OR location LIKE ?)"
        params += [f"%{query}%"] * 3

    sql += " ORDER BY score DESC NULLS LAST, found_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_for_report():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, title, company, location, url, score, reasoning, status, found_at
        FROM jobs
        WHERE status != 'rejected'
        ORDER BY score DESC NULLS LAST, found_at DESC
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_stats():
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COUNT(*)                                              AS total,
            COUNT(CASE WHEN status = 'new'           THEN 1 END) AS new,
            COUNT(CASE WHEN status = 'reviewed'      THEN 1 END) AS reviewed,
            COUNT(CASE WHEN status = 'applied'       THEN 1 END) AS applied,
            COUNT(CASE WHEN status = 'rejected'      THEN 1 END) AS rejected,
            COUNT(CASE WHEN status = 'auto_rejected' THEN 1 END) AS auto_rejected,
            ROUND(AVG(CASE WHEN score IS NOT NULL THEN score END), 2) AS avg_score
        FROM jobs
    """).fetchone()
    conn.close()
    return dict(row)
