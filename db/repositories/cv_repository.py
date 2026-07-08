import json
from db.connection import get_connection


def insert(filename: str, raw_text: str, parsed: dict) -> int:
    """Insert a new CV profile, making it the active one. Returns the new row id."""
    conn = get_connection()
    conn.execute("UPDATE cv_profiles SET is_active = 0")
    cursor = conn.execute(
        "INSERT INTO cv_profiles (filename, raw_text, parsed, is_active) VALUES (?, ?, ?, 1)",
        (filename, raw_text, json.dumps(parsed, ensure_ascii=False))
    )
    id_ = cursor.lastrowid
    conn.commit()
    conn.close()
    return id_


def get_active() -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM cv_profiles WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["parsed"] = json.loads(d["parsed"]) if d["parsed"] else {}
    return d


def list_all() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM cv_profiles ORDER BY created_at DESC, id DESC"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d["parsed"] = json.loads(d["parsed"]) if d["parsed"] else {}
        result.append(d)
    return result


def set_active(id_: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE cv_profiles SET is_active = 0")
    conn.execute("UPDATE cv_profiles SET is_active = 1 WHERE id = ?", (id_,))
    conn.commit()
    conn.close()
