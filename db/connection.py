import sqlite3
import os
import time

from config import AGENT, DB_BACKEND, POSTGRES

_pg_pool = None


def _get_pg_pool():
    """psycopg2 is only imported here (lazily) so DB_BACKEND=sqlite — every test,
    and any local install that hasn't set up Postgres — never needs it installed."""
    global _pg_pool
    if _pg_pool is None:
        from psycopg2.pool import ThreadedConnectionPool
        _pg_pool = ThreadedConnectionPool(
            minconn=1, maxconn=10,
            host=POSTGRES["host"], port=POSTGRES["port"], dbname=POSTGRES["dbname"],
            user=POSTGRES["user"], password=POSTGRES["password"],
        )
    return _pg_pool


class _PGCursor:
    """Adds SQLite's cursor.lastrowid semantics on top of a psycopg2 cursor, via an
    auto-appended RETURNING id on plain INSERT statements (every table's primary key
    in this schema is named `id`) — lazy so callers that never touch .lastrowid pay
    no extra fetch. Everything else (fetchone/fetchall/rowcount, row["col"] access
    via RealDictCursor) passes straight through to the wrapped cursor."""

    def __init__(self, cur, is_insert):
        self._cur = cur
        self._is_insert = is_insert
        self._lastrowid = None
        self._lastrowid_fetched = False

    @property
    def lastrowid(self):
        if self._is_insert and not self._lastrowid_fetched:
            row = self._cur.fetchone()
            self._lastrowid = row["id"] if row else None
            self._lastrowid_fetched = True
        return self._lastrowid

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _PGConnection:
    """Adapts a pooled psycopg2 connection to the sqlite3.Connection surface every
    repository already uses: conn.execute(sql, params) with '?' placeholders,
    conn.executescript(sql), row["col"] dict-style access, conn.commit(), conn.close().
    close() returns the connection to the pool instead of actually closing it —
    real connections crossing the WireGuard tunnel are too expensive to open per call."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        # DictCursor (not RealDictCursor) — DictRow supports BOTH row["col"] and
        # row[0] positional access, matching sqlite3.Row's actual behavior. A good
        # deal of this codebase was written against sqlite3.Row and does use
        # positional indexing (e.g. `.fetchone()[0]` for a COUNT(*)); RealDictCursor
        # only supports string keys and raised KeyError: 0 on every one of those.
        from psycopg2.extras import DictCursor
        translated = sql.replace("?", "%s")
        is_insert = translated.strip().upper().startswith("INSERT") and "RETURNING" not in translated.upper()
        if is_insert:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor(cursor_factory=DictCursor)
        cur.execute(translated, params)
        return _PGCursor(cur, is_insert)

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        cur.close()

    def commit(self):
        self._conn.commit()

    def close(self):
        _get_pg_pool().putconn(self._conn)


def _connect_postgres() -> "_PGConnection":
    pool = _get_pg_pool()
    last_error = None
    for attempt in range(3):
        try:
            return _PGConnection(pool.getconn())
        except Exception as e:  # transient tunnel/VPS blip — retry with backoff
            last_error = e
            time.sleep(0.5 * (attempt + 1))
    raise last_error


def _connect_sqlite() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(AGENT["db_path"]), exist_ok=True)
    conn = sqlite3.connect(AGENT["db_path"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_connection():
    if DB_BACKEND == "postgres":
        return _connect_postgres()
    return _connect_sqlite()
