import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from db.repositories import preference_repository


def test_get_latest_empty():
    assert preference_repository.get_latest() is None


def test_save_and_get():
    preference_repository.save("ACCEPT[rate=explicit; conf=HIGH]", applied_count=5, rejected_count=10)
    profile = preference_repository.get_latest()
    assert profile is not None
    assert profile["content"] == "ACCEPT[rate=explicit; conf=HIGH]"
    assert profile["applied_count"] == 5
    assert profile["rejected_count"] == 10


def test_get_latest_returns_most_recent():
    preference_repository.save("OLD PROFILE", applied_count=1, rejected_count=2)
    preference_repository.save("NEW PROFILE", applied_count=3, rejected_count=6)
    profile = preference_repository.get_latest()
    assert profile["content"] == "NEW PROFILE"
    assert profile["applied_count"] == 3
