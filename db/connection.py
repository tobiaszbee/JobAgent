import sqlite3
import os

from config import AGENT


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(AGENT["db_path"]), exist_ok=True)
    conn = sqlite3.connect(AGENT["db_path"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
