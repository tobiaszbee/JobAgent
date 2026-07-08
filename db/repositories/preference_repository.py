import json
from db.connection import get_connection


def get_latest() -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM preference_profiles ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    if result.get("content_format") == "json":
        result["signals"] = json.loads(result["content"])
    else:
        result["signals"] = []
    return result


def save(signals: list[dict], applied_count: int, rejected_count: int) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO preference_profiles (content, content_format, applied_count, rejected_count, updated_at)
           VALUES (?, 'json', ?, ?, CURRENT_TIMESTAMP)""",
        (json.dumps(signals), applied_count, rejected_count),
    )
    conn.commit()
    conn.close()
