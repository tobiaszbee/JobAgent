from evaluator.scorer import build_system_prompt, _build_examples_section, _build_user_message


def _ex(**kwargs):
    """Minimal job dict for example lists."""
    return {
        "title": "PHP Developer",
        "company": "Acme Corp",
        "location": "Poland (Remote)",
        "description": "Symfony experience required.",
        **kwargs,
    }


class TestBuildExamplesSection:
    def test_both_empty_returns_empty_string(self):
        assert _build_examples_section([], []) == ""

    def test_positive_example_appears_in_output(self):
        section = _build_examples_section([_ex(company="GoodCo")], [])
        assert "APPLIED TO" in section
        assert "PHP Developer" in section
        assert "GoodCo" in section

    def test_negative_example_appears_in_output(self):
        section = _build_examples_section([], [_ex(score_reason="On-site only, no remote")])
        assert "REJECTED" in section
        assert "On-site only" in section

    def test_negative_without_score_reason_does_not_crash(self):
        section = _build_examples_section([], [_ex()])
        assert "REJECTED" in section

    def test_description_truncated_in_positive(self):
        section = _build_examples_section([_ex(description="x" * 500)], [])
        assert "x" * 201 not in section  # truncated to 200 chars in the snippet

    def test_both_sections_appear_together(self):
        section = _build_examples_section([_ex(company="GoodCo")],
                                          [_ex(company="BadCo", score_reason="On-site")])
        assert "APPLIED TO" in section
        assert "REJECTED" in section


class TestBuildSystemPrompt:
    def test_candidate_profile_in_prompt(self):
        prompt = build_system_prompt({}, [], [], candidate_profile="My custom profile here")
        assert "My custom profile here" in prompt

    def test_preferred_criteria_in_prompt(self):
        prompt = build_system_prompt({"preferred": ["Symfony", "Kubernetes"]}, [], [])
        assert "Symfony" in prompt
        assert "Kubernetes" in prompt

    def test_required_in_prompt_rejected_not(self):
        prompt = build_system_prompt({"required": ["php"], "rejected": ["junior"]}, [], [])
        assert "php" in prompt
        assert "junior" not in prompt

    def test_must_have_section_in_prompt(self):
        prompt = build_system_prompt({"required": ["Symfony", "PHP"]}, [], [])
        assert "MUST HAVE" in prompt
        assert "Symfony" in prompt
        assert "PHP" in prompt

    def test_submit_score_tool_instruction_present(self):
        prompt = build_system_prompt({}, [], [])
        assert "submit_score" in prompt
        assert '"score"' not in prompt
        assert '"dealbreakers_found"' not in prompt

    def test_empty_preferred_shows_placeholder(self):
        prompt = build_system_prompt({}, [], [])
        assert "(none configured)" in prompt

    def test_positive_examples_embedded_in_prompt(self):
        pos = [_ex(company="GoodCo")]
        prompt = build_system_prompt({}, pos, [], candidate_profile="Profile")
        assert "GoodCo" in prompt
        assert "APPLIED TO" in prompt


class TestBuildUserMessage:
    def test_contains_all_job_fields(self):
        job = _ex()
        msg = _build_user_message(job)
        assert "PHP Developer" in msg
        assert "Acme Corp" in msg
        assert "Poland (Remote)" in msg
        assert "Symfony experience" in msg

    def test_full_description_not_truncated(self):
        job = _ex(description="x" * 5000)
        msg = _build_user_message(job)
        assert "x" * 5000 in msg

    def test_none_description_does_not_crash(self):
        job = _ex(description=None)
        msg = _build_user_message(job)
        assert "Title: PHP Developer" in msg

    def test_empty_description_does_not_crash(self):
        job = _ex(description="")
        msg = _build_user_message(job)
        assert "Company: Acme Corp" in msg
