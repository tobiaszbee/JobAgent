import pytest
from db.repositories import cv_repository

_PARSED = {
    "stack": ["PHP 8", "Symfony", "MySQL"],
    "years_experience": 8,
    "seniority": "Senior",
    "location": "Poland",
    "remote_preference": "fully remote",
    "raw_summary": "Senior PHP engineer with 8 years experience.",
}


def _insert(filename="cv.pdf", parsed=None):
    return cv_repository.insert(filename, "raw CV text", parsed or _PARSED)


class TestInsert:
    def test_returns_integer_id(self):
        id_ = _insert()
        assert isinstance(id_, int) and id_ > 0

    def test_newly_inserted_is_active(self):
        _insert()
        profile = cv_repository.get_active()
        assert profile is not None
        assert profile["filename"] == "cv.pdf"

    def test_inserting_second_deactivates_first(self):
        _insert("first.pdf")
        _insert("second.pdf")
        active = cv_repository.get_active()
        assert active["filename"] == "second.pdf"

    def test_parsed_json_round_trips_correctly(self):
        _insert()
        profile = cv_repository.get_active()
        assert profile["parsed"]["stack"] == ["PHP 8", "Symfony", "MySQL"]
        assert profile["parsed"]["years_experience"] == 8


class TestGetActive:
    def test_returns_none_when_empty(self):
        assert cv_repository.get_active() is None

    def test_returns_active_profile(self):
        _insert()
        assert cv_repository.get_active() is not None

    def test_parsed_is_dict_not_string(self):
        _insert()
        profile = cv_repository.get_active()
        assert isinstance(profile["parsed"], dict)


class TestListAll:
    def test_empty_returns_empty_list(self):
        assert cv_repository.list_all() == []

    def test_returns_all_profiles_newest_first(self):
        _insert("first.pdf")
        _insert("second.pdf")
        profiles = cv_repository.list_all()
        assert len(profiles) == 2
        assert profiles[0]["filename"] == "second.pdf"

    def test_parsed_is_dict_in_list(self):
        _insert()
        profiles = cv_repository.list_all()
        assert isinstance(profiles[0]["parsed"], dict)


class TestSetActive:
    def test_activates_older_profile(self):
        id1 = _insert("first.pdf")
        _insert("second.pdf")
        cv_repository.set_active(id1)
        assert cv_repository.get_active()["filename"] == "first.pdf"

    def test_only_one_active_at_a_time(self):
        id1 = _insert("first.pdf")
        id2 = _insert("second.pdf")
        cv_repository.set_active(id1)
        active_count = sum(1 for p in cv_repository.list_all() if p["is_active"])
        assert active_count == 1
