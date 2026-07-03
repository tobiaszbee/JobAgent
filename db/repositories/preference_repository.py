from db.connection import get_connection


def get_latest() -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM preference_profiles ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save(content: str, applied_count: int, rejected_count: int) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO preference_profiles (content, applied_count, rejected_count, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
        (content, applied_count, rejected_count),
    )
    conn.commit()
    conn.close()
