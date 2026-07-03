from preference_agent.runner import _build_prompt, _job_line


def _job(title="Dev", company="Corp", location="Remote", description="PHP Symfony", rejection_reason=None, score_reason=None):
    return {
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "rejection_reason": rejection_reason,
        "score_reason": score_reason,
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
    rejected = []
    prompt = _build_prompt(applied, rejected)
    assert "APPLIED (1 jobs)" in prompt
    assert "SWE" in prompt
    assert "BigCo" in prompt


def test_build_prompt_rejected_section():
    applied = []
    rejected = [_job("Junior Dev", "AgencyCo", rejection_reason="stawka za niska")]
    prompt = _build_prompt(applied, rejected)
    assert "REJECTED (1 jobs)" in prompt
    assert "Junior Dev" in prompt
    assert "stawka za niska" in prompt


def test_build_prompt_existing_profile_included():
    prompt = _build_prompt([], [], existing_profile="ACCEPT[rate=explicit]")
    assert "ACCEPT[rate=explicit]" in prompt
    assert "PREVIOUS PROFILE" in prompt


def test_build_prompt_no_existing_profile_shows_none():
    prompt = _build_prompt([], [])
    assert "none" in prompt


def test_build_prompt_applied_empty():
    prompt = _build_prompt([], [_job("X", "Y")])
    assert "APPLIED (0 jobs)" in prompt


def test_build_prompt_rejected_empty():
    prompt = _build_prompt([_job("X", "Y")], [])
    assert "REJECTED (0 jobs)" in prompt


def test_build_prompt_description_truncated():
    long_desc = "PHP " * 200  # 800 chars
    applied = [_job(description=long_desc)]
    prompt = _build_prompt(applied, [])
    # Description should be capped at 180 chars in the job line
    lines = [l for l in prompt.splitlines() if "PHP" in l and '"' in l]
    assert any(len(l) < 400 for l in lines)
