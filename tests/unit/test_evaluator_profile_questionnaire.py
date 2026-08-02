from unittest.mock import patch

from evaluator.profile import load_questionnaire_preferences


@patch("evaluator.profile.candidate_preferences_repository.get_active", return_value=None)
def test_empty_when_no_active_prefs(mock_prefs):
    assert load_questionnaire_preferences() == ""


@patch("evaluator.profile.candidate_preferences_repository.get_active", return_value={})
def test_empty_when_all_fields_blank(mock_prefs):
    assert load_questionnaire_preferences() == ""


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_includes_header_and_work_mode(mock_prefs):
    mock_prefs.return_value = {"work_mode": ["remote", "hybrid"]}
    section = load_questionnaire_preferences()
    assert "CANDIDATE QUESTIONNAIRE" in section
    assert "Work mode: remote, hybrid" in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_remote_countries_and_hybrid_cities(mock_prefs):
    mock_prefs.return_value = {
        "remote_countries": ["Poland", "Germany"],
        "hybrid_cities": ["Warsaw"],
    }
    section = load_questionnaire_preferences()
    assert "Remote must be available in: Poland, Germany" in section
    assert "OK with hybrid in: Warsaw" in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_seniority_levels(mock_prefs):
    mock_prefs.return_value = {"seniority_levels": ["senior", "lead"]}
    section = load_questionnaire_preferences()
    assert "Seniority level(s) wanted: senior, lead" in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_all_list_fields_rendered_with_labels(mock_prefs):
    mock_prefs.return_value = {
        "role_types": ["backend"],
        "preferred_company_types": ["product"],
        "excluded_company_types": ["agency"],
        "preferred_industries": ["fintech"],
        "excluded_industries": ["gambling"],
        "extra_tech": ["Rust"],
        "avoided_tech": ["PHP"],
    }
    section = load_questionnaire_preferences()
    assert "Desired role type(s): backend" in section
    assert "Prefers company type(s): product" in section
    assert "Wants to avoid company type(s): agency" in section
    assert "Prefers industry/industries: fintech" in section
    assert "Wants to avoid industry/industries: gambling" in section
    assert "Also interested in: Rust" in section
    assert "Wants to avoid working with: PHP" in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_salary_min_with_currency(mock_prefs):
    mock_prefs.return_value = {"salary_min": 20000, "salary_currency": "PLN"}
    section = load_questionnaire_preferences()
    assert "Minimum salary: 20000 PLN" in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_salary_min_without_currency_has_no_trailing_space(mock_prefs):
    mock_prefs.return_value = {"salary_min": 20000, "salary_currency": None}
    section = load_questionnaire_preferences()
    assert "Minimum salary: 20000" in section
    assert "20000 \n" not in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_languages_rendered_with_cefr_level(mock_prefs):
    mock_prefs.return_value = {
        "languages": [{"language": "English", "level": "C1"}, {"language": "German", "level": "B2"}]
    }
    section = load_questionnaire_preferences()
    assert "Languages: English (C1), German (B2)" in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_open_notes_quoted(mock_prefs):
    mock_prefs.return_value = {"open_notes": "I really want to work on ML infra."}
    section = load_questionnaire_preferences()
    assert 'In their own words: "I really want to work on ML infra."' in section


@patch("evaluator.profile.candidate_preferences_repository.get_active")
def test_open_notes_blank_string_omitted(mock_prefs):
    mock_prefs.return_value = {"open_notes": "   "}
    assert load_questionnaire_preferences() == ""
