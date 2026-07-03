from evaluator.scorer import build_system_prompt, _build_preferences_section


def _criteria():
    return {"required": [], "rejected": [], "preferred": []}


def test_preferences_section_empty_when_no_profile():
    section = _build_preferences_section("")
    assert section == ""


def test_preferences_section_empty_for_whitespace():
    section = _build_preferences_section("   \n  ")
    assert section == ""


def test_preferences_section_present_when_profile_given():
    section = _build_preferences_section("ACCEPT[company=product; conf=HIGH]")
    assert "LEARNED PREFERENCE PROFILE" in section
    assert "ACCEPT[company=product; conf=HIGH]" in section


def test_build_system_prompt_includes_preferences():
    profile = "ACCEPT[rate=explicit; conf=HIGH; n=5/5]\nREJECT[company=agency; conf=ABSOLUTE; n=10/10]"
    prompt = build_system_prompt(_criteria(), [], [], learned_preferences=profile)
    assert "LEARNED PREFERENCE PROFILE" in prompt
    assert "ACCEPT[rate=explicit" in prompt
    assert "REJECT[company=agency" in prompt


def test_build_system_prompt_without_preferences_no_section():
    prompt = build_system_prompt(_criteria(), [], [])
    assert "LEARNED PREFERENCE PROFILE" not in prompt


def test_build_system_prompt_preferences_before_examples():
    """Profile section should appear before the examples section."""
    profile = "ACCEPT[x=y]"
    examples = [{"title": "Dev", "company": "Co", "description": "PHP code here"}]
    prompt = build_system_prompt(_criteria(), examples, [], learned_preferences=profile)
    prefs_pos = prompt.index("LEARNED PREFERENCE PROFILE")
    examples_pos = prompt.index("EXAMPLES OF JOBS I APPLIED")
    assert prefs_pos < examples_pos


def test_build_system_prompt_works_with_none_as_empty():
    """learned_preferences defaults to empty string — no crash."""
    prompt = build_system_prompt(_criteria(), [], [], learned_preferences="")
    assert "REQUIRED" in prompt  # basic sanity
