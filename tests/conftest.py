import os

# Set before any project module is imported so config.py doesn't raise.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import pytest
import config
from db.migrations import init_db


@pytest.fixture(autouse=True)
def test_db(tmp_path, monkeypatch):
    """Redirect DB to a temp file and initialise schema before every test."""
    monkeypatch.setitem(config.AGENT, "db_path", str(tmp_path / "test.db"))
    init_db()


@pytest.fixture
def flask_client(test_db):
    """Flask test client with a fresh DB already initialised."""
    from web.app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
