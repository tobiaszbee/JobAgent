from src.db.connection import get_connection

TYPES = ["title", "location", "required", "preferred", "rejected"]


def get_all():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM criteria ORDER BY type, value"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_active(type_):
    conn = get_connection()
    rows = conn.execute(
        "SELECT value FROM criteria WHERE type = ? AND active = 1",
        (type_,)
    ).fetchall()
    conn.close()
    return [row["value"] for row in rows]


def get_criteria_dict():
    return {
        "titles":    get_active("title"),
        "locations": get_active("location"),
        "required":  get_active("required"),
        "preferred": get_active("preferred"),
        "rejected":  get_active("rejected"),
        "min_score": 6.0,
    }


def insert(type_, value):
    if type_ not in TYPES:
        raise ValueError(f"Invalid type: {type_}")
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO criteria (type, value) VALUES (?, ?)",
        (type_, value.strip())
    )
    conn.commit()
    conn.close()


def toggle(id_, active):
    conn = get_connection()
    conn.execute(
        "UPDATE criteria SET active = ? WHERE id = ?",
        (1 if active else 0, id_)
    )
    conn.commit()
    conn.close()


def delete(id_):
    conn = get_connection()
    conn.execute("DELETE FROM criteria WHERE id = ?", (id_,))
    conn.commit()
    conn.close()


def seed_from_config(config_criteria):
    mapping = {
        "titles":    "title",
        "locations": "location",
        "required":  "required",
        "preferred": "preferred",
        "rejected":  "rejected",
    }
    conn = get_connection()
    for key, type_ in mapping.items():
        for value in config_criteria.get(key, []):
            conn.execute(
                "INSERT OR IGNORE INTO criteria (type, value) VALUES (?, ?)",
                (type_, value)
            )
    conn.commit()
    conn.close()
    print("Criteria seeded from config.")
