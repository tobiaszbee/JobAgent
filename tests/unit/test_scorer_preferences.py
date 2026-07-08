from evaluator.scorer import build_system_prompt, _build_preferences_section


def _criteria():
    return {"required": [], "rejected": [], "preferred": []}


# --- list[dict] interface (primary path) ---

def test_preferences_section_empty_for_empty_list():
    section = _build_preferences_section([])
    assert section == ""


def test_preferences_section_present_when_signals_given():
    signals = [{"type": "ACCEPT", "dim": "company", "value": "product", "conf": "HIGH"}]
    section = _build_preferences_section(signals)
    assert "LEARNED PREFERENCE PROFILE" in section
    assert "ACCEPT[company=product" in section


def test_preferences_section_filters_neutral_signals():
    signals = [
        {"type": "ACCEPT", "dim": "company", "value": "product", "conf": "HIGH"},
        {"type": "NEUTRAL", "dim": "contract_form"},
        {"type": "REJECT", "dim": "company", "value": "agency", "conf": "ABSOLUTE"},
    ]
    section = _build_preferences_section(signals)
    assert "ACCEPT[company=product" in section
    assert "REJECT[company=agency" in section
    assert "NEUTRAL[" not in section


def test_preferences_section_empty_when_only_neutral_signals():
    signals = [{"type": "NEUTRAL", "dim": "contract_form"}, {"type": "NEUTRAL", "dim": "domain"}]
    section = _build_preferences_section(signals)
    assert section == ""


def test_preferences_section_includes_legend():
    signals = [{"type": "ACCEPT", "dim": "x", "value": "y", "conf": "HIGH"}]
    section = _build_preferences_section(signals)
    assert "Interpretation" in section
    assert "MUST HAVE always wins" in section


def test_preferences_section_infer_soft_signal_in_legend():
    signals = [{"type": "INFER", "dim": "min_rate", "value": "15000", "n_total": 5}]
    section = _build_preferences_section(signals)
    assert "INFER" in section
    assert "do NOT penalize" in section


# --- string interface (backward compat for e2e test D-5) ---

def test_preferences_section_empty_when_no_profile():
    section = _build_preferences_section("")
    assert section == ""


def test_preferences_section_empty_for_whitespace():
    section = _build_preferences_section("   \n  ")
    assert section == ""


def test_preferences_section_filters_neutral_lines():
    profile = "ACCEPT[company=product; conf=HIGH]\nNEUTRAL[contract_form; no_signal]\nREJECT[company=agency; conf=ABSOLUTE]"
    section = _build_preferences_section(profile)
    assert "ACCEPT[company=product" in section
    assert "REJECT[company=agency" in section
    assert "NEUTRAL[" not in section


def test_preferences_section_empty_when_only_neutral_str():
    section = _build_preferences_section("NEUTRAL[contract_form; no_signal]\nNEUTRAL[domain; no_signal]")
    assert section == ""


# --- build_system_prompt integration ---

def test_build_system_prompt_includes_preferences():
    signals = [
        {"type": "ACCEPT", "dim": "rate", "value": "explicit", "conf": "HIGH", "n_match": 5, "n_total": 5},
        {"type": "REJECT", "dim": "company", "value": "agency", "conf": "ABSOLUTE", "n_match": 10, "n_total": 10},
    ]
    prompt = build_system_prompt(_criteria(), [], [], learned_preferences=signals)
    assert "LEARNED PREFERENCE PROFILE" in prompt
    assert "ACCEPT[rate=explicit" in prompt
    assert "REJECT[company=agency" in prompt


def test_build_system_prompt_without_preferences_no_section():
    prompt = build_system_prompt(_criteria(), [], [])
    assert "LEARNED PREFERENCE PROFILE" not in prompt


def test_build_system_prompt_preferences_before_examples():
    signals = [{"type": "ACCEPT", "dim": "x", "value": "y"}]
    examples = [{"title": "Dev", "company": "Co", "description": "PHP code here"}]
    prompt = build_system_prompt(_criteria(), examples, [], learned_preferences=signals)
    prefs_pos = prompt.index("LEARNED PREFERENCE PROFILE")
    examples_pos = prompt.index("EXAMPLES OF JOBS I APPLIED")
    assert prefs_pos < examples_pos


def test_build_system_prompt_works_with_empty_list():
    prompt = build_system_prompt(_criteria(), [], [], learned_preferences=[])
    assert "PREFERRED" in prompt
