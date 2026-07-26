from db.connection import get_connection
from config import DB_BACKEND

VALID_TYPES = {"title", "location", "required", "preferred", "rejected", "search_query"}


def get_all() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM criteria ORDER BY type, value"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_active(type_: str) -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT value FROM criteria WHERE type = ? AND is_active = 1",
        (type_,)
    ).fetchall()
    conn.close()
    return [row["value"] for row in rows]


def get_active_dict() -> dict:
    return {
        "search_queries": get_active("search_query"),
        "titles":         get_active("title"),
        "locations":      get_active("location"),
        "required":       get_active("required"),
        "preferred":      get_active("preferred"),
        "rejected":       get_active("rejected"),
    }


def insert(type_: str, value: str) -> None:
    if type_ not in VALID_TYPES:
        raise ValueError(f"Invalid criteria type: {type_!r}. Must be one of {VALID_TYPES}")
    conn = get_connection()
    sql = ("INSERT INTO criteria (type, value) VALUES (?, ?) ON CONFLICT (type, value) DO NOTHING"
           if DB_BACKEND == "postgres" else
           "INSERT OR IGNORE INTO criteria (type, value) VALUES (?, ?)")
    conn.execute(sql, (type_, value.strip()))
    conn.commit()
    conn.close()


def toggle(id_: int, is_active: bool) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE criteria SET is_active = ? WHERE id = ?",
        (1 if is_active else 0, id_)
    )
    conn.commit()
    conn.close()


def delete(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM criteria WHERE id = ?", (id_,))
    conn.commit()
    conn.close()
