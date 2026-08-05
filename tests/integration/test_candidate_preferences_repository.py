import pytest
from db.repositories import candidate_preferences_repository as repo
from db.repositories import cv_repository


def _cv_id() -> int:
    return cv_repository.insert("cv.pdf", "raw text", {"stack": ["PHP"]})


class TestInsert:
    def test_returns_integer_id(self):
        id_ = repo.insert(_cv_id(), {"salary_min": 15000})
        assert isinstance(id_, int) and id_ > 0

    def test_empty_fields_creates_blank_row(self):
        id_ = repo.insert(_cv_id())
        assert isinstance(id_, int) and id_ > 0
        active = repo.get_active()
        assert active["salary_min"] is None

    def test_newly_inserted_is_active(self):
        repo.insert(_cv_id(), {"salary_min": 20000})
        active = repo.get_active()
        assert active is not None
        assert active["salary_min"] == 20000

    def test_inserting_second_deactivates_first(self):
        repo.insert(_cv_id(), {"salary_min": 10000})
        repo.insert(_cv_id(), {"salary_min": 30000})
        active = repo.get_active()
        assert active["salary_min"] == 30000

    def test_cv_profile_id_stored(self):
        cv_id = _cv_id()
        repo.insert(cv_id, {"salary_min": 10000})
        active = repo.get_active()
        assert active["cv_profile_id"] == cv_id

    def test_json_list_field_round_trips(self):
        repo.insert(_cv_id(), {"remote_countries": ["PL", "DE", "AT"]})
        active = repo.get_active()
        assert active["remote_countries"] == ["PL", "DE", "AT"]

    def test_languages_field_round_trips(self):
        langs = [{"language": "english", "level": "C1"}, {"language": "polish", "level": "native"}]
        repo.insert(_cv_id(), {"languages": langs})
        active = repo.get_active()
        assert active["languages"] == langs

    def test_explicit_empty_list_distinct_from_unset(self):
        repo.insert(_cv_id(), {"extra_tech": []})
        active = repo.get_active()
        assert active["extra_tech"] == []

    def test_show_jobs_without_salary_defaults_to_one(self):
        repo.insert(_cv_id())
        active = repo.get_active()
        assert active["show_jobs_without_salary"] == 1

    def test_invalid_field_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid candidate_preferences field"):
            repo.insert(_cv_id(), {"not_a_real_field": "x"})

    def test_cv_profile_id_can_be_none(self):
        id_ = repo.insert(None, {"salary_min": 5000})
        assert isinstance(id_, int)
        assert repo.get_active()["cv_profile_id"] is None


class TestGetActive:
    def test_returns_none_when_empty(self):
        assert repo.get_active() is None

    def test_json_fields_are_native_types_not_strings(self):
        repo.insert(_cv_id(), {"work_mode": ["remote", "hybrid"], "role_types": ["developer"]})
        active = repo.get_active()
        assert isinstance(active["work_mode"], list)
        assert isinstance(active["role_types"], list)

    def test_unset_json_field_is_none(self):
        repo.insert(_cv_id(), {"salary_min": 1000})
        active = repo.get_active()
        assert active["avoided_tech"] is None


class TestListAll:
    def test_empty_returns_empty_list(self):
        assert repo.list_all() == []

    def test_returns_all_newest_first(self):
        repo.insert(_cv_id(), {"salary_min": 1000})
        repo.insert(_cv_id(), {"salary_min": 2000})
        rows = repo.list_all()
        assert len(rows) == 2
        assert rows[0]["salary_min"] == 2000

    def test_json_fields_deserialized_in_list(self):
        repo.insert(_cv_id(), {"extra_tech": ["Rust"]})
        rows = repo.list_all()
        assert rows[0]["extra_tech"] == ["Rust"]


class TestSetActive:
    def test_activates_older_row(self):
        id1 = repo.insert(_cv_id(), {"salary_min": 1000})
        repo.insert(_cv_id(), {"salary_min": 2000})
        repo.set_active(id1)
        assert repo.get_active()["salary_min"] == 1000

    def test_only_one_active_at_a_time(self):
        id1 = repo.insert(_cv_id(), {"salary_min": 1000})
        repo.insert(_cv_id(), {"salary_min": 2000})
        repo.set_active(id1)
        active_count = sum(1 for r in repo.list_all() if r["is_active"])
        assert active_count == 1


class TestUpdate:
    def test_updates_existing_row_in_place(self):
        id_ = repo.insert(_cv_id(), {"salary_min": 1000})
        repo.update(id_, {"salary_min": 5000})
        active = repo.get_active()
        assert active["salary_min"] == 5000

    def test_update_json_field(self):
        id_ = repo.insert(_cv_id(), {"remote_countries": ["PL"]})
        repo.update(id_, {"remote_countries": ["PL", "DE"]})
        active = repo.get_active()
        assert active["remote_countries"] == ["PL", "DE"]

    def test_partial_update_leaves_other_fields_untouched(self):
        id_ = repo.insert(_cv_id(), {"salary_min": 1000, "salary_currency": "PLN"})
        repo.update(id_, {"salary_min": 2000})
        active = repo.get_active()
        assert active["salary_min"] == 2000
        assert active["salary_currency"] == "PLN"

    def test_empty_fields_is_a_no_op(self):
        id_ = repo.insert(_cv_id(), {"salary_min": 1000})
        repo.update(id_, {})
        assert repo.get_active()["salary_min"] == 1000

    def test_invalid_field_raises_value_error(self):
        id_ = repo.insert(_cv_id())
        with pytest.raises(ValueError, match="Invalid candidate_preferences field"):
            repo.update(id_, {"bogus": 1})


class TestDelete:
    def test_deletes_row(self):
        id_ = repo.insert(_cv_id(), {"salary_min": 1000})
        repo.delete(id_)
        assert repo.list_all() == []
