import hashlib
from db.connection import get_connection


def _generate_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


def exists(url: str) -> bool:
    conn = get_connection()
    row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row is not None


def exists_by_title_company(title: str, company: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM jobs WHERE LOWER(title) = LOWER(?) AND LOWER(company) = LOWER(?)",
        (title.strip(), company.strip())
    ).fetchone()
    conn.close()
    return row is not None


def insert(
    title: str,
    company: str,
    location: str,
    url: str,
    source: str,
    source_id: str | None = None,
    description: str | None = None,
) -> str | None:
    if exists(url):
        return None
    if company and exists_by_title_company(title, company):
        return None
    job_id = _generate_id(url)
    conn = get_connection()
    conn.execute(
        """INSERT INTO jobs (id, title, company, location, url, description, source, source_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, title, company, location, url, description, source, source_id)
    )
    conn.commit()
    conn.close()
    return job_id


def get_all_urls() -> set[str]:
    """Return all known job URLs as a set for fast duplicate checking."""
    conn = get_connection()
    rows = conn.execute("SELECT url FROM jobs").fetchall()
    conn.close()
    return {row["url"] for row in rows}


def get_missing_descriptions() -> list[dict]:
    """Jobs without a description that are not yet scored — candidates for description retry."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, url FROM jobs WHERE (description IS NULL OR description = '') AND score IS NULL ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_description(job_id: str, description: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (description, job_id)
    )
    conn.commit()
    conn.close()


def update_score(job_id: str, score: float, reason: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET score = ?, score_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (score, reason, job_id)
    )
    conn.commit()
    conn.close()


def update_status(job_id: str, status: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, job_id)
    )
    conn.commit()
    conn.close()


def update_score_and_status(job_id: str, score: float, reason: str, status: str) -> None:
    """Atomic update of score and status in a single transaction."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET score = ?, score_reason = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (score, reason, status, job_id)
    )
    conn.commit()
    conn.close()


def get_new() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_unscored() -> list[dict]:
    """Jobs that are new and have not been scored yet. Used by the evaluator."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' AND score IS NULL AND description IS NOT NULL AND description != '' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_by_status(status: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = ? ORDER BY score DESC NULLS LAST, created_at DESC",
        (status,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_examples(
    limit_positive: int = 8,
    limit_negative: int = 5,
) -> tuple[list[dict], list[dict]]:
    conn = get_connection()
    positive = conn.execute(
        "SELECT * FROM jobs WHERE status = 'applied' ORDER BY updated_at DESC LIMIT ?",
        (limit_positive,)
    ).fetchall()
    negative = conn.execute(
        "SELECT * FROM jobs WHERE status = 'rejected' ORDER BY updated_at DESC LIMIT ?",
        (limit_negative,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in positive], [dict(r) for r in negative]


def search(
    status: str | None = None,
    min_score: float | None = None,
    query: str | None = None,
    source: str | None = None,
) -> list[dict]:
    conn = get_connection()
    sql = "SELECT * FROM jobs WHERE 1=1"
    params: list = []

    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)

    if min_score is not None:
        sql += " AND (score >= ? OR score IS NULL)"
        params.append(min_score)

    if query:
        sql += " AND (title LIKE ? OR company LIKE ? OR location LIKE ?)"
        params += [f"%{query}%"] * 3

    if source:
        sql += " AND source = ?"
        params.append(source)

    sql += " ORDER BY score DESC NULLS LAST, created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_stats() -> dict:
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
    last = conn.execute(
        "SELECT finished_at FROM sessions WHERE status = 'done' ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    result = dict(row)
    result["last_run"] = last["finished_at"] if last else None
    return result
