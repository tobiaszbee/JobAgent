from preference_agent.profile import render_signals


def test_accept_renders_full():
    s = [{"type": "ACCEPT", "dim": "company_type", "value": "product_saas", "conf": "HIGH", "n_match": 3, "n_total": 3}]
    line = render_signals(s)
    assert line == "ACCEPT[company_type=product_saas; conf=HIGH; n=3/3]"


def test_reject_with_note():
    s = [{"type": "REJECT", "dim": "company_type", "value": "agency", "conf": "ABSOLUTE", "n_match": 5, "n_total": 5, "note": "body shop"}]
    line = render_signals(s)
    assert line == "REJECT[company_type=agency; conf=ABSOLUTE; n=5/5]: body shop"


def test_infer_with_n_total():
    s = [{"type": "INFER", "dim": "min_rate", "value": "80k", "n_total": 3}]
    line = render_signals(s)
    assert line == "INFER[min_rate=80k; from=3 examples]"


def test_infer_without_value():
    s = [{"type": "INFER", "dim": "work_culture"}]
    line = render_signals(s)
    assert line == "INFER[work_culture]"


def test_neutral_renders():
    s = [{"type": "NEUTRAL", "dim": "contract_form"}]
    line = render_signals(s)
    assert line == "NEUTRAL[contract_form; no_signal]"


def test_accept_without_optional_fields():
    s = [{"type": "ACCEPT", "dim": "tech_stack", "value": "php"}]
    line = render_signals(s)
    assert line == "ACCEPT[tech_stack=php]"


def test_multiple_signals_joined_by_newline():
    signals = [
        {"type": "ACCEPT", "dim": "company_type", "value": "product_saas", "conf": "HIGH", "n_match": 3, "n_total": 3},
        {"type": "NEUTRAL", "dim": "compensation"},
    ]
    out = render_signals(signals)
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("ACCEPT[")
    assert lines[1].startswith("NEUTRAL[")


def test_empty_list_returns_empty_string():
    assert render_signals([]) == ""
