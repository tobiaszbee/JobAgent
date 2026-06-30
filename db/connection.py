import sqlite3
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import AGENT


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(AGENT["db_path"]), exist_ok=True)
    conn = sqlite3.connect(AGENT["db_path"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
