import json
from db.repositories import preference_repository

_SIGNALS = [{"type": "ACCEPT", "dim": "rate", "value": "explicit", "conf": "HIGH"}]
_SIGNALS2 = [{"type": "REJECT", "dim": "company_type", "value": "agency", "conf": "ABSOLUTE"}]


def test_get_latest_empty():
    assert preference_repository.get_latest() is None


def test_save_and_get():
    preference_repository.save(_SIGNALS, applied_count=5, rejected_count=10)
    profile = preference_repository.get_latest()
    assert profile is not None
    assert profile["content_format"] == "json"
    assert profile["signals"] == _SIGNALS
    assert profile["applied_count"] == 5
    assert profile["rejected_count"] == 10


def test_get_latest_returns_most_recent():
    preference_repository.save(_SIGNALS, applied_count=1, rejected_count=2)
    preference_repository.save(_SIGNALS2, applied_count=3, rejected_count=6)
    profile = preference_repository.get_latest()
    assert profile["signals"] == _SIGNALS2
    assert profile["applied_count"] == 3


def test_legacy_text_format_returns_empty_signals():
    """Rows written before G (content_format=text) get signals=[] so scorer skips them safely."""
    from db.connection import get_connection
    conn = get_connection()
    conn.execute(
        "INSERT INTO preference_profiles (content, content_format, applied_count, rejected_count) VALUES (?, 'text', ?, ?)",
        ("ACCEPT[rate=explicit; conf=HIGH]", 1, 0),
    )
    conn.commit()
    conn.close()
    profile = preference_repository.get_latest()
    assert profile["content_format"] == "text"
    assert profile["signals"] == []
