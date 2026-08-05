import uuid

from db.repositories import criteria_repository, job_repository
from collector.filters import apply_keyword_filter, title_banned_reason, _contains_keyword


def _insert_job(title="PHP Developer", company="Acme", description="Symfony expertise required.", url=None):
    # uuid suffix: job_postings is shared/never-truncated, and this title default repeats across tests.
    return job_repository.insert(
        title=title,
        company=company,
        location="Remote",
        url=url or f"https://example.com/{title.lower().replace(' ', '-')}-{uuid.uuid4().hex}",
        source="linkedin",
        description=description,
    )


class TestRunE2Filter:
    def test_no_criteria_returns_early(self):
        _insert_job()
        result = apply_keyword_filter()
        assert result == {"checked": 0, "auto_rejected": 0, "rejected_ids": []}

    def test_only_rejected_criteria_no_match_passes(self):
        criteria_repository.insert("rejected", "junior")
        _insert_job(title="Senior PHP Developer", description="Backend role")
        result = apply_keyword_filter()
        assert result["auto_rejected"] == 0

    def test_rejected_keyword_in_title_auto_rejects(self):
        criteria_repository.insert("rejected", "junior")
        _insert_job(title="Junior PHP Developer", description="Backend role")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "auto_rejected"

    def test_rejected_keyword_in_description_auto_rejects(self):
        criteria_repository.insert("rejected", "on-site")
        _insert_job(title="PHP Developer", description="This is an on-site role in Warsaw")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "auto_rejected"

    def test_required_keyword_missing_from_title_and_description_auto_rejects(self):
        criteria_repository.insert("required", "php")
        _insert_job(title="Java Developer", description="Spring Boot experience needed")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "auto_rejected"

    def test_required_keyword_in_title_passes(self):
        criteria_repository.insert("required", "php")
        _insert_job(title="Senior PHP Developer", description="Spring Boot experience needed")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "new"

    def test_required_keyword_in_description_passes(self):
        criteria_repository.insert("required", "php")
        _insert_job(title="Backend Developer", description="We use PHP and Symfony")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "new"

    def test_required_keyword_job_without_description_uses_title(self):
        criteria_repository.insert("required", "php")
        _insert_job(title="PHP Developer", description=None)
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "new"

    def test_no_required_criteria_no_required_filter(self):
        criteria_repository.insert("rejected", "junior")
        _insert_job(title="Java Developer", description="Spring Boot role")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "new"

    def test_required_auto_reject_stores_reason(self):
        criteria_repository.insert("required", "php")
        _insert_job(title="Jewelry Designer", description="Creative design role")
        apply_keyword_filter()
        reason = job_repository.search()[0]["score_reason"]
        assert "Auto-rejected" in reason
        assert "php" in reason.lower()

    def test_rejected_check_runs_before_required_check(self):
        criteria_repository.insert("required", "php")
        criteria_repository.insert("rejected", "internship")
        _insert_job(title="PHP Internship", description="PHP role for students")
        apply_keyword_filter()
        reason = job_repository.search()[0]["score_reason"]
        assert "internship" in reason  # rejected, not required-missing

    def test_matching_is_case_insensitive(self):
        criteria_repository.insert("rejected", "junior")
        _insert_job(title="JUNIOR PHP Developer", description="Entry level role")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "auto_rejected"

    def test_rejected_check_takes_priority_over_required(self):
        criteria_repository.insert("required", "php")
        criteria_repository.insert("rejected", "junior")
        _insert_job(title="Junior PHP Developer", description="PHP Symfony role")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "auto_rejected"

    def test_score_reason_stored_on_auto_reject(self):
        criteria_repository.insert("rejected", "cobol")
        _insert_job(title="COBOL Developer", description="Legacy banking role")
        apply_keyword_filter()
        assert "Auto-rejected" in job_repository.search()[0]["score_reason"]

    def test_returns_correct_counts(self):
        criteria_repository.insert("rejected", "php")
        _insert_job(title="PHP Developer", description="Good role", url="https://a.com/1")
        _insert_job(title="Java Developer", description="Spring role", url="https://a.com/2")
        result = apply_keyword_filter()
        assert result["checked"] == 2
        assert result["auto_rejected"] == 1

    def test_already_auto_rejected_jobs_skipped(self):
        criteria_repository.insert("required", "php")
        job_id = _insert_job(title="Java Developer", description="Spring role")
        job_repository.update_score_and_status(job_id, 0.0, "LinkedIn unavailable", "auto_rejected")
        result = apply_keyword_filter()
        assert result["checked"] == 0

    def test_uses_the_given_jobs_list_instead_of_fetching_its_own(self):
        # Regression guard: collector/runner.py shares one get_new() fetch between
        # the language and keyword filters instead of each independently pulling
        # the full 'new' pool, confirms an explicit list is actually honored.
        criteria_repository.insert("rejected", "junior")
        job_id = _insert_job(title="Senior PHP Developer", description="Backend role")
        explicit_jobs = [{"id": job_id, "title": "Junior PHP Developer", "company": "Acme", "description": "Backend role"}]
        result = apply_keyword_filter(explicit_jobs)
        assert result["checked"] == 1
        assert result["rejected_ids"] == [job_id]


class TestTitleBannedReason:
    def test_no_rejected_keywords_passes(self):
        assert title_banned_reason("Junior PHP Developer", []) is None

    def test_matching_keyword_in_title_rejects(self):
        reason = title_banned_reason("Junior PHP Developer", ["junior"])
        assert reason is not None
        assert "junior" in reason.lower()

    def test_no_matching_keyword_passes(self):
        assert title_banned_reason("Senior PHP Developer", ["junior"]) is None

    def test_matching_is_case_insensitive(self):
        assert title_banned_reason("JUNIOR PHP Developer", ["junior"]) is not None

    def test_whole_word_match_no_false_positive_on_substring(self):
        # "php" should not match inside an unrelated word like "phpstorm-integration"... but should match standalone
        assert title_banned_reason("Graphics Designer", ["php"]) is None


class TestContainsKeywordSymbolBoundaries:
    # Regression for the audit's "\b never matches symbol-suffixed keywords"
    # finding: plain \b{kw}\b requires a \w/non-\w transition on *both* sides,
    # but "c++" followed by a space has a non-word char on both sides of that
    # trailing boundary, so \b never fires there, silently making c++/c#/.net
    # inert in both the required and rejected keyword lists.
    def test_plain_word_still_matches_as_whole_word(self):
        assert _contains_keyword("senior php developer", "php") is True

    def test_plain_word_still_rejects_substring_match(self):
        assert _contains_keyword("phpunit specialist", "php") is False

    def test_cpp_matches_before_a_space(self):
        assert _contains_keyword("senior c++ developer", "c++") is True

    def test_cpp_matches_at_end_of_string(self):
        assert _contains_keyword("looking for a c++ engineer", "c++") is True

    def test_csharp_matches(self):
        assert _contains_keyword("c# backend developer", "c#") is True

    def test_dotnet_matches(self):
        assert _contains_keyword(".net developer wanted", ".net") is True

    def test_csharp_does_not_match_inside_a_longer_alnum_run(self):
        assert _contains_keyword("c#hello backend developer", "c#") is False

    def test_required_cpp_keyword_end_to_end(self):
        criteria_repository.insert("required", "c++")
        _insert_job(title="Senior C++ Developer", description="Embedded systems role")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "new"

    def test_rejected_dotnet_keyword_end_to_end(self):
        criteria_repository.insert("rejected", ".net")
        _insert_job(title="Backend Developer", description="We use .NET and C#")
        apply_keyword_filter()
        assert job_repository.search()[0]["status"] == "auto_rejected"
