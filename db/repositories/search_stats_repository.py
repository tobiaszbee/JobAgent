from db.connection import get_connection


def record(session_id: int, source: str, search_query: str, location: str, cards_found: int, new_found: int) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO search_stats (session_id, source, search_query, location, cards_found, new_found)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, source, search_query, location, cards_found, new_found),
    )
    conn.commit()
    conn.close()


def get_query_summary(source: str) -> list[dict]:
    """Per search_query totals across all recorded runs — zero_result_searches counts
    individual (query, location) calls that found no cards at all, not full runs.
    A starting point for later "consistently dead query" analysis, not wired into
    any exclusion decision yet."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT
               search_query,
               COUNT(*)                                        AS total_searches,
               SUM(CASE WHEN cards_found = 0 THEN 1 ELSE 0 END) AS zero_result_searches,
               SUM(new_found)                                  AS total_new_found,
               MAX(searched_at)                                AS last_searched_at
           FROM search_stats
           WHERE source = ?
           GROUP BY search_query
           ORDER BY search_query""",
        (source,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
