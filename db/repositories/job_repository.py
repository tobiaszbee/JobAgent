import hashlib
import json
from db.connection import get_connection
from db.types import JobRow, JobStats


def _generate_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


def insert(
    title: str,
    company: str,
    location: str,
    url: str,
    source: str,
    source_id: str | None = None,
    description: str | None = None,
) -> str | None:
    conn = get_connection()
    try:
        url_match = conn.execute(
            "SELECT id FROM jobs WHERE url = ?", (url,)
        ).fetchone()
        if url_match:
            return None

        if company:
            title_company_match = conn.execute(
                "SELECT id FROM jobs WHERE LOWER(title) = LOWER(?) AND LOWER(company) = LOWER(?)",
                (title.strip(), company.strip()),
            ).fetchone()
            if title_company_match:
                return None

        job_id = _generate_id(url)
        conn.execute(
            """INSERT INTO jobs (id, title, company, location, url, description, source, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, title, company, location, url, description, source, source_id),
        )
        conn.commit()
        return job_id
    finally:
        conn.close()


def get_all_urls() -> set[str]:
    """Return all known job URLs as a set for fast duplicate checking."""
    conn = get_connection()
    rows = conn.execute("SELECT url FROM jobs").fetchall()
    conn.close()
    return {row["url"] for row in rows}


def get_missing_descriptions() -> list[dict]:
    """LinkedIn jobs without a description that are not yet scored — candidates for backfill."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, url FROM jobs WHERE source = 'linkedin'"
        " AND (description IS NULL OR description = '') AND score IS NULL ORDER BY created_at DESC"
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


def update_status(job_id: str, status: str, rejection_reason: str | None = None) -> None:
    conn = get_connection()
    if status == "rejected" and rejection_reason is not None:
        conn.execute(
            "UPDATE jobs SET status = ?, rejection_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, rejection_reason or None, job_id)
        )
    else:
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


def get_unscored() -> list[JobRow]:
    """Jobs that are new and have not been scored yet. Used by the evaluator."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' AND score IS NULL AND description IS NOT NULL AND description != '' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_new_with_descriptions() -> list[dict]:
    """All 'new' jobs that have descriptions — used for force-rescore."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' AND description IS NOT NULL AND description != '' ORDER BY created_at DESC"
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
    limit_positive: int = 25,
    limit_negative: int = 25,
) -> tuple[list[JobRow], list[JobRow]]:
    conn = get_connection()
    positive = conn.execute(
        "SELECT * FROM jobs WHERE status = 'applied' ORDER BY updated_at DESC LIMIT ?",
        (limit_positive,)
    ).fetchall()
    negative = conn.execute(
        "SELECT * FROM jobs WHERE status = 'rejected' "
        "ORDER BY (rejection_reason IS NOT NULL) DESC, updated_at DESC LIMIT ?",
        (limit_negative,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in positive], [dict(r) for r in negative]


def get_all_feedback() -> tuple[list[dict], list[dict]]:
    conn = get_connection()
    applied = conn.execute(
        "SELECT title, company, location, description, score_reason FROM jobs WHERE status = 'applied' ORDER BY updated_at DESC"
    ).fetchall()
    rejected = conn.execute(
        "SELECT title, company, location, description, rejection_reason, score_reason FROM jobs WHERE status = 'rejected' ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in applied], [dict(r) for r in rejected]


def get_feedback_since(since_timestamp: str) -> tuple[list[dict], list[dict]]:
    conn = get_connection()
    applied = conn.execute(
        "SELECT title, company, location, description, score_reason FROM jobs WHERE status = 'applied' AND updated_at > ? ORDER BY updated_at DESC",
        (since_timestamp,),
    ).fetchall()
    rejected = conn.execute(
        "SELECT title, company, location, description, rejection_reason, score_reason FROM jobs WHERE status = 'rejected' AND updated_at > ? ORDER BY updated_at DESC",
        (since_timestamp,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in applied], [dict(r) for r in rejected]


def search(
    status: str | None = None,
    min_score: float | None = None,
    query: str | None = None,
    source: str | None = None,
) -> list[JobRow]:
    conn = get_connection()
    sql = "SELECT * FROM jobs WHERE 1=1"
    params: list = []

    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)

    if min_score is not None:
        sql += " AND score >= ?"
        params.append(min_score)

    if query:
        sql += " AND (title LIKE ? OR company LIKE ? OR location LIKE ? OR description LIKE ? OR score_reason LIKE ? OR rank_reason LIKE ?)"
        params += [f"%{query}%"] * 6

    if source:
        sql += " AND source = ?"
        params.append(source)

    sql += " ORDER BY listwise_rank ASC NULLS LAST, rerank_score DESC NULLS LAST, embedding_score DESC NULLS LAST, score DESC NULLS LAST, created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _filter_sql(statuses: list[str], date_from: str | None, date_to: str | None) -> tuple[str, list]:
    placeholders = ",".join("?" * len(statuses))
    sql = f"WHERE status IN ({placeholders})"
    params: list = list(statuses)
    if date_from:
        sql += " AND created_at >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND created_at <= ?"
        params.append(date_to + " 23:59:59")
    return sql, params


def count_by_filter(statuses: list[str], date_from: str | None = None, date_to: str | None = None) -> int:
    if not statuses:
        return 0
    where, params = _filter_sql(statuses, date_from, date_to)
    conn = get_connection()
    n = conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0]
    conn.close()
    return n


def delete_by_filter(statuses: list[str], date_from: str | None = None, date_to: str | None = None) -> int:
    if not statuses:
        return 0
    where, params = _filter_sql(statuses, date_from, date_to)
    conn = get_connection()
    n = conn.execute(f"DELETE FROM jobs {where}", params).rowcount
    conn.commit()
    conn.close()
    return n


def update_structured_data(job_id: str, data: dict) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET structured_data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(data, ensure_ascii=False), job_id),
    )
    conn.commit()
    conn.close()


def update_ranking_scores(
    job_id: str,
    embedding_score: float | None,
    rerank_score: float | None,
    listwise_rank: int | None,
) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE jobs
           SET embedding_score = ?, rerank_score = ?, listwise_rank = ?,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (embedding_score, rerank_score, listwise_rank, job_id),
    )
    conn.commit()
    conn.close()


def get_jobs_for_ranking(limit: int = 200) -> list[dict]:
    """New jobs with descriptions that haven't been listwise-ranked yet."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM jobs
           WHERE status = 'new'
             AND description IS NOT NULL AND description != ''
             AND listwise_rank IS NULL
           ORDER BY created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_applied_job_ids() -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT id FROM jobs WHERE status = 'applied'").fetchall()
    conn.close()
    return [r["id"] for r in rows]


def get_rejected_job_ids() -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT id FROM jobs WHERE status = 'rejected'").fetchall()
    conn.close()
    return [r["id"] for r in rows]


def count_decisions() -> int:
    """Total number of applied + rejected decisions. Used for auto-distillation trigger."""
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('applied', 'rejected')"
    ).fetchone()[0]
    conn.close()
    return n


def get_stats() -> JobStats:
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
    ranked = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE listwise_rank IS NOT NULL AND status = 'new'"
    ).fetchone()[0]
    conn.close()
    result = dict(row)
    result["last_run"] = last["finished_at"] if last else None
    result["ranked"] = ranked
    return result
