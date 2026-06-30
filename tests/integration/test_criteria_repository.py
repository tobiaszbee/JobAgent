import pytest
from db.repositories import criteria_repository


class TestInsert:
    def test_insert_valid_type_succeeds(self):
        criteria_repository.insert("title", "PHP Developer")
        assert len(criteria_repository.get_all()) == 1

    def test_insert_invalid_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid criteria type"):
            criteria_repository.insert("bad_type", "value")

    def test_duplicate_type_value_is_ignored(self):
        criteria_repository.insert("title", "PHP Developer")
        criteria_repository.insert("title", "PHP Developer")
        assert len(criteria_repository.get_all()) == 1

    def test_same_value_different_type_both_stored(self):
        criteria_repository.insert("title", "Symfony")
        criteria_repository.insert("preferred", "Symfony")
        assert len(criteria_repository.get_all()) == 2

    def test_value_leading_trailing_whitespace_stripped(self):
        criteria_repository.insert("title", "  PHP Developer  ")
        assert criteria_repository.get_all()[0]["value"] == "PHP Developer"

    def test_all_valid_types_accepted(self):
        for type_ in ("title", "location", "required", "preferred", "rejected"):
            criteria_repository.insert(type_, f"value-{type_}")
        assert len(criteria_repository.get_all()) == 5


class TestGetActive:
    def test_returns_active_values_only(self):
        criteria_repository.insert("title", "PHP Dev")
        criteria_repository.insert("title", "Java Dev")
        java_id = next(c["id"] for c in criteria_repository.get_all() if c["value"] == "Java Dev")
        criteria_repository.toggle(java_id, False)
        active = criteria_repository.get_active("title")
        assert "PHP Dev" in active
        assert "Java Dev" not in active

    def test_returns_empty_when_none_exist(self):
        assert criteria_repository.get_active("title") == []


class TestGetActiveDict:
    def test_all_keys_present(self):
        d = criteria_repository.get_active_dict()
        assert set(d.keys()) == {"titles", "locations", "required", "preferred", "rejected"}

    def test_each_type_mapped_to_correct_key(self):
        criteria_repository.insert("title", "PHP Dev")
        criteria_repository.insert("location", "Poland")
        criteria_repository.insert("preferred", "Symfony")
        criteria_repository.insert("required", "AWS")
        criteria_repository.insert("rejected", "on-site only")
        d = criteria_repository.get_active_dict()
        assert "PHP Dev" in d["titles"]
        assert "Poland" in d["locations"]
        assert "Symfony" in d["preferred"]
        assert "AWS" in d["required"]
        assert "on-site only" in d["rejected"]


class TestToggle:
    def test_deactivate_hides_from_get_active(self):
        criteria_repository.insert("title", "PHP Dev")
        item_id = criteria_repository.get_all()[0]["id"]
        criteria_repository.toggle(item_id, False)
        assert criteria_repository.get_active("title") == []

    def test_reactivate_restores_to_get_active(self):
        criteria_repository.insert("title", "PHP Dev")
        item_id = criteria_repository.get_all()[0]["id"]
        criteria_repository.toggle(item_id, False)
        criteria_repository.toggle(item_id, True)
        assert "PHP Dev" in criteria_repository.get_active("title")


class TestDelete:
    def test_deletes_criterion_by_id(self):
        criteria_repository.insert("title", "PHP Dev")
        item_id = criteria_repository.get_all()[0]["id"]
        criteria_repository.delete(item_id)
        assert criteria_repository.get_all() == []
