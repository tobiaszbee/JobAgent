import config
from db.connection import get_connection
from db.migrations import init_db
from db.repositories import job_repository, dismissed_item_repository


def _insert_job(url="https://example.com/1"):
    return job_repository.insert(
        title="Backend Dev", company="AcmeCo", location="Remote",
        url=url, source="linkedin", description="PHP role.",
    )


class TestCascadeDeleteOnFreshInstall:
    # The autouse test_db fixture already ran init_db() against a fresh temp DB before
    # this test runs, so these exercise the CREATE TABLE ... ON DELETE CASCADE path.
    def test_deleting_job_with_dismissed_item_succeeds(self):
        job_id = _insert_job()
        dismissed_item_repository.insert(job_id, "con", "No salary shown", "not an issue for me")
        conn = get_connection()
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        assert dismissed_item_repository.get_for_job(job_id) == []

    def test_deleting_job_with_embedding_succeeds(self):
        job_id = _insert_job()
        conn = get_connection()
        conn.execute("INSERT INTO job_embeddings (job_id, embedding, model) VALUES (?, ?, ?)",
                     (job_id, "[0.1, 0.2]", "voyage-3-large"))
        conn.commit()
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        remaining = conn.execute("SELECT * FROM job_embeddings WHERE job_id = ?", (job_id,)).fetchall()
        conn.close()
        assert remaining == []


class TestCascadeDeleteMigrationFromOldSchema:
    """Simulates a real pre-existing database created before ON DELETE CASCADE was
    added — exactly the shape that caused the reported bug (DELETE /api/jobs failing
    with "FOREIGN KEY constraint failed" on any job with a dismissed score item)."""

    def _downgrade_to_old_schema(self):
        conn = get_connection()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript("""
            DROP TABLE dismissed_score_items;
            CREATE TABLE dismissed_score_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL REFERENCES jobs(id),
                item_type   TEXT NOT NULL,
                item_text   TEXT NOT NULL,
                reason      TEXT NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            DROP TABLE job_embeddings;
            CREATE TABLE job_embeddings (
                job_id     TEXT PRIMARY KEY REFERENCES jobs(id),
                embedding  TEXT,
                model      TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

    def test_old_schema_reproduces_the_reported_bug(self):
        self._downgrade_to_old_schema()
        job_id = _insert_job()
        dismissed_item_repository.insert(job_id, "con", "No salary shown", "not an issue for me")
        conn = get_connection()
        try:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            raised = False
        except Exception as e:
            raised = "FOREIGN KEY constraint failed" in str(e)
        finally:
            conn.close()
        assert raised, "expected the old (pre-fix) schema to reproduce the reported FOREIGN KEY error"

    def test_rerunning_init_db_fixes_existing_database_without_losing_data(self):
        self._downgrade_to_old_schema()
        job_id = _insert_job()
        dismissed_item_repository.insert(job_id, "con", "No salary shown", "not an issue for me")
        conn = get_connection()
        conn.execute("INSERT INTO job_embeddings (job_id, embedding, model) VALUES (?, ?, ?)",
                     (job_id, "[0.1, 0.2]", "voyage-3-large"))
        conn.commit()
        conn.close()

        init_db()  # re-running against an already-initialised (but old-shaped) DB

        # Pre-existing data survived the rebuild.
        assert dismissed_item_repository.get_for_job(job_id)[0]["item_text"] == "No salary shown"
        conn = get_connection()
        assert conn.execute("SELECT * FROM job_embeddings WHERE job_id = ?", (job_id,)).fetchone() is not None
        conn.close()

        # And the delete that used to fail now succeeds.
        conn = get_connection()
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        assert dismissed_item_repository.get_for_job(job_id) == []

    def test_rerunning_init_db_is_idempotent(self):
        # Calling init_db() repeatedly (as happens on every app start) must not error
        # once the schema is already fixed.
        init_db()
        init_db()
        _insert_job()


class TestWouldApplySchema:
    def test_jobs_has_would_apply_columns(self):
        conn = get_connection()
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        conn.close()
        assert "would_apply" in columns
        assert "would_apply_reason" in columns


class TestSearchQueryPruningSchema:
    def test_jobs_has_search_query_column(self):
        conn = get_connection()
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        conn.close()
        assert "search_query" in columns

    def test_excluded_search_queries_table_exists(self):
        conn = get_connection()
        conn.execute("INSERT INTO excluded_search_queries (source, search_query, reason) VALUES (?, ?, ?)",
                     ("linkedin", "PHP Developer", "reason"))
        conn.commit()
        row = conn.execute("SELECT * FROM excluded_search_queries").fetchone()
        conn.close()
        assert row["search_query"] == "PHP Developer"

    def test_excluded_search_queries_unique_per_source_and_query(self):
        conn = get_connection()
        conn.execute("INSERT INTO excluded_search_queries (source, search_query, reason) VALUES (?, ?, ?)",
                     ("linkedin", "PHP Developer", "reason 1"))
        conn.commit()
        raised = False
        try:
            conn.execute("INSERT INTO excluded_search_queries (source, search_query, reason) VALUES (?, ?, ?)",
                         ("linkedin", "PHP Developer", "reason 2"))
            conn.commit()
        except Exception:
            raised = True
        conn.close()
        assert raised

    def test_rerunning_init_db_after_column_already_added_is_idempotent(self):
        init_db()
        _insert_job()
