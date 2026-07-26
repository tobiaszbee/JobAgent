"""Unit tests for the Postgres adapter classes in db/connection.py. These test the
?->%s translation and RETURNING-id/lastrowid emulation logic in isolation with mock
cursors — no real Postgres server needed. The Postgres path also needs one real,
manual smoke test against an actual server before it's trusted in production (no
Docker available on this dev machine to automate that here — see plan)."""
from unittest.mock import MagicMock
from db.connection import _PGCursor, _PGConnection


class TestPGCursorLastrowid:
    def test_lastrowid_returns_id_from_returning_row(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": 42}
        cur = _PGCursor(mock_cur, is_insert=True)
        assert cur.lastrowid == 42
        mock_cur.fetchone.assert_called_once()

    def test_lastrowid_is_lazy_and_cached(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": 7}
        cur = _PGCursor(mock_cur, is_insert=True)
        assert cur.lastrowid == 7
        assert cur.lastrowid == 7
        mock_cur.fetchone.assert_called_once()  # second access uses the cached value

    def test_lastrowid_none_when_no_row_returned(self):
        """e.g. an ON CONFLICT DO NOTHING that inserted nothing."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        cur = _PGCursor(mock_cur, is_insert=True)
        assert cur.lastrowid is None

    def test_lastrowid_none_for_non_insert_without_touching_cursor(self):
        mock_cur = MagicMock()
        cur = _PGCursor(mock_cur, is_insert=False)
        assert cur.lastrowid is None
        mock_cur.fetchone.assert_not_called()

    def test_other_attributes_delegate_to_wrapped_cursor(self):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [{"a": 1}]
        cur = _PGCursor(mock_cur, is_insert=False)
        assert cur.fetchall() == [{"a": 1}]
        assert cur.rowcount is mock_cur.rowcount


class TestPGConnectionExecute:
    def _conn_with_mock_cursor(self):
        mock_pg_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": 1}
        mock_pg_conn.cursor.return_value = mock_cur
        return _PGConnection(mock_pg_conn), mock_cur

    def test_translates_question_mark_placeholders(self):
        conn, mock_cur = self._conn_with_mock_cursor()
        conn.execute("SELECT * FROM jobs WHERE id = ? AND status = ?", ("j1", "new"))
        called_sql = mock_cur.execute.call_args[0][0]
        assert "?" not in called_sql
        assert called_sql.count("%s") == 2

    def test_appends_returning_id_to_plain_insert(self):
        conn, mock_cur = self._conn_with_mock_cursor()
        conn.execute("INSERT INTO criteria (type, value) VALUES (?, ?)", ("required", "PHP"))
        called_sql = mock_cur.execute.call_args[0][0]
        assert "RETURNING id" in called_sql

    def test_does_not_double_append_returning(self):
        conn, mock_cur = self._conn_with_mock_cursor()
        conn.execute("INSERT INTO jobs (id, title) VALUES (?, ?) RETURNING id", ("j1", "Dev"))
        called_sql = mock_cur.execute.call_args[0][0]
        assert called_sql.count("RETURNING id") == 1

    def test_select_is_untouched_by_insert_logic(self):
        conn, mock_cur = self._conn_with_mock_cursor()
        conn.execute("SELECT * FROM jobs WHERE status = ?", ("new",))
        called_sql = mock_cur.execute.call_args[0][0]
        assert "RETURNING" not in called_sql

    def test_close_returns_connection_to_pool_not_closes_it(self, monkeypatch):
        import db.connection as db_connection
        mock_pg_conn = MagicMock()
        conn = _PGConnection(mock_pg_conn)
        mock_pool = MagicMock()
        monkeypatch.setattr(db_connection, "_get_pg_pool", lambda: mock_pool)
        conn.close()
        mock_pool.putconn.assert_called_once_with(mock_pg_conn)
        mock_pg_conn.close.assert_not_called()
