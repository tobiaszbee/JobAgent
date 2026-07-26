from preference_agent.runner import _build_prompt, _job_line, _build_dismissed_section


def _job(title="Dev", company="Corp", location="Remote", description="PHP Symfony", rejection_reason=None, score_reason=None, source=None):
    return {
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "rejection_reason": rejection_reason,
        "score_reason": score_reason,
        "source": source,
    }


def test_job_line_basic():
    line = _job_line(_job("Senior PHP Dev", "AcmeCo", "Poland (Remote)"))
    assert "Senior PHP Dev" in line
    assert "AcmeCo" in line
    assert "Poland (Remote)" in line


def test_job_line_includes_reason_when_requested():
    j = _job(rejection_reason="stawka za niska")
    line = _job_line(j, include_reason=True)
    assert "stawka za niska" in line


def test_job_line_no_reason_without_flag():
    j = _job(rejection_reason="stawka za niska")
    line = _job_line(j, include_reason=False)
    assert "stawka za niska" not in line


def test_job_line_falls_back_to_score_reason():
    j = _job(rejection_reason=None, score_reason="too junior")
    line = _job_line(j, include_reason=True)
    assert "too junior" in line


def test_build_prompt_applied_section():
    applied = [_job("SWE", "BigCo", "USA (Remote)")]
    prompt = _build_prompt(applied, [])
    assert "APPLIED (1 jobs)" in prompt
    assert "SWE" in prompt
    assert "BigCo" in prompt


def test_build_prompt_rejected_section():
    rejected = [_job("Junior Dev", "AgencyCo", rejection_reason="stawka za niska")]
    prompt = _build_prompt([], rejected)
    assert "REJECTED (1 jobs" in prompt
    assert "Junior Dev" in prompt
    assert "stawka za niska" in prompt


def test_build_prompt_applied_empty():
    prompt = _build_prompt([], [_job("X", "Y")])
    assert "APPLIED (0 jobs)" in prompt


def test_build_prompt_rejected_empty():
    prompt = _build_prompt([_job("X", "Y")], [])
    assert "REJECTED (0 jobs)" in prompt


def test_job_line_strips_linkedin_junk():
    # Regression guard: _job_line used to slice job["description"] raw, letting
    # LinkedIn's page-chrome junk pollute the preference-distillation prompt.
    j = _job(description="Real content about the role.\nSet alert for similar jobs\nUnrelated junk.", source="linkedin")
    line = _job_line(j)
    assert "Real content about the role." in line
    assert "Unrelated junk" not in line


def test_build_prompt_description_not_truncated():
    long_desc = "PHP " * 200  # 800 chars
    prompt = _build_prompt([_job(description=long_desc)], [])
    assert long_desc.strip() in prompt


def test_build_prompt_caps_rejected_at_max_and_shows_most_recent():
    from preference_agent.runner import _MAX_REJECTED
    # Feed _MAX_REJECTED + 5 jobs; first ones in the list are most recent (DESC order from DB)
    rejected = [_job(title=f"Job {i}") for i in range(_MAX_REJECTED + 5)]
    prompt = _build_prompt([], rejected)
    # Most recent (first in list) must appear; oldest (beyond cap) must be omitted
    assert "Job 0" in prompt
    assert f"Job {_MAX_REJECTED}" not in prompt
    assert "older omitted" in prompt


def test_build_dismissed_section_empty_returns_empty_string():
    assert _build_dismissed_section([]) == ""


def test_build_dismissed_section_formats_con():
    items = [{"item_type": "con", "item_text": "UK-based, timezone concern", "reason": "not an issue for me",
              "title": "Backend Dev", "company": "AcmeCo"}]
    section = _build_dismissed_section(items)
    assert "CON" in section
    assert "UK-based, timezone concern" in section
    assert "not an issue for me" in section
    assert "Backend Dev" in section
    assert "AcmeCo" in section


def test_build_dismissed_section_formats_pro():
    items = [{"item_type": "pro", "item_text": "Fully remote", "reason": "actually I prefer hybrid",
              "title": "Dev", "company": "Corp"}]
    section = _build_dismissed_section(items)
    assert "PRO" in section
