import json
from db.connection import get_connection

# List-valued fields, stored as JSON text — matches the convention already used by
# jobs.structured_data and cv_profiles.parsed.
_JSON_FIELDS = {
    "work_mode", "remote_countries", "hybrid_cities", "seniority_levels", "role_types",
    "preferred_company_types", "excluded_company_types", "preferred_industries",
    "excluded_industries", "extra_tech", "avoided_tech", "languages",
}
_SCALAR_FIELDS = {
    "salary_min", "salary_max", "salary_currency", "show_jobs_without_salary", "open_notes",
}
_VALID_FIELDS = _JSON_FIELDS | _SCALAR_FIELDS


def _serialize(fields: dict) -> dict:
    out = {}
    for key, value in fields.items():
        if key not in _VALID_FIELDS:
            raise ValueError(f"Invalid candidate_preferences field: {key!r}. Must be one of {sorted(_VALID_FIELDS)}")
        out[key] = json.dumps(value, ensure_ascii=False) if key in _JSON_FIELDS and value is not None else value
    return out


def _deserialize(row) -> dict:
    d = dict(row)
    for key in _JSON_FIELDS:
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


def insert(cv_profile_id: int | None, fields: dict | None = None) -> int:
    """Create a new active preferences snapshot, deactivating any previous one.
    `fields` may include any subset of the known columns — every question is optional,
    so an empty dict (or omitting it) is valid and creates a blank snapshot."""
    data = _serialize(fields or {})
    data["cv_profile_id"] = cv_profile_id

    conn = get_connection()
    conn.execute("UPDATE candidate_preferences SET is_active = 0")
    columns = list(data.keys())
    placeholders = ", ".join("?" * len(columns))
    column_list = ", ".join(columns)
    cursor = conn.execute(
        f"INSERT INTO candidate_preferences ({column_list}, is_active) VALUES ({placeholders}, 1)",
        list(data.values()),
    )
    id_ = cursor.lastrowid
    conn.commit()
    conn.close()
    return id_


def get_active() -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM candidate_preferences WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _deserialize(row)


def list_all() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM candidate_preferences ORDER BY created_at DESC, id DESC"
    ).fetchall()
    conn.close()
    return [_deserialize(r) for r in rows]


def set_active(id_: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE candidate_preferences SET is_active = 0")
    conn.execute("UPDATE candidate_preferences SET is_active = 1 WHERE id = ?", (id_,))
    conn.commit()
    conn.close()


def update(id_: int, fields: dict) -> None:
    """Partially update an existing preferences row in place — e.g. editing one answer
    later without creating a whole new versioned snapshot."""
    if not fields:
        return
    data = _serialize(fields)
    set_clause = ", ".join(f"{k} = ?" for k in data)
    conn = get_connection()
    conn.execute(
        f"UPDATE candidate_preferences SET {set_clause} WHERE id = ?",
        [*data.values(), id_],
    )
    conn.commit()
    conn.close()


def delete(id_: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM candidate_preferences WHERE id = ?", (id_,))
    conn.commit()
    conn.close()
