from db.connection import get_connection


def exclude(source: str, search_query: str, reason: str) -> None:
    """Idempotent — re-excluding an already-excluded query updates its reason
    instead of erroring, so a re-run with fresher stats keeps the log current."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO excluded_search_queries (source, search_query, reason)
           VALUES (?, ?, ?)
           ON CONFLICT(source, search_query) DO UPDATE SET reason = excluded.reason""",
        (source, search_query, reason),
    )
    conn.commit()
    conn.close()


def get_excluded(source: str) -> dict[str, str]:
    """search_query -> reason, for filtering a source's query list before collection."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT search_query, reason FROM excluded_search_queries WHERE source = ?",
        (source,),
    ).fetchall()
    conn.close()
    return {row["search_query"]: row["reason"] for row in rows}


def get_all() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM excluded_search_queries ORDER BY excluded_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def reinstate(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM excluded_search_queries WHERE id = ?", (id_,))
    conn.commit()
    conn.close()
