import os
from dotenv import load_dotenv

# Load real keys from .env / .env.test before setting the fake test default,
# so e2e tests pick up real credentials without manually exporting env vars.
load_dotenv(".env.test", override=False)
load_dotenv(".env", override=False)

# Fall back to a fake key so unit/integration tests run without any .env file.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("VOYAGE_API_KEY", "test-voyage-key-not-real")

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
