from contextlib import contextmanager
from unittest.mock import patch
from db.repositories import job_repository
from evaluator.runner import run


def _insert_scoreable(url="https://example.com/1", **kwargs):
    """Insert a job that has a description and is ready to be scored."""
    defaults = dict(title="PHP Developer", company="Acme Corp",
                    location="Poland", source="linkedin",
                    description="Symfony expertise required.")
    return job_repository.insert(**{**defaults, "url": url, **kwargs})


def _good_score(**overrides):
    return {
        "score": 7.5,
        "score_reason": "Good PHP and Symfony match",
        **overrides,
    }


@contextmanager
def _patched_run(score_result=None, side_effect=None):
    """Patch load_active_profile, build_system_prompt, and score_job together."""
    score_kwargs = {"side_effect": side_effect} if side_effect else {"return_value": score_result or _good_score()}
    with patch("evaluator.runner.load_active_profile", return_value="fake profile"):
        with patch("evaluator.runner.build_system_prompt", return_value="fake prompt"):
            with patch("evaluator.runner.score_job", **score_kwargs) as mock_score:
                yield mock_score


class TestEvaluatorRunner:
    def test_no_jobs_returns_zero_counts(self):
        result = run()
        assert result == {"jobs_scored": 0}

    def test_job_without_description_is_skipped(self):
        job_repository.insert("No desc", "Co", "PL", "https://a.com/1", "linkedin")
        with _patched_run() as mock_score:
            run()
        mock_score.assert_not_called()

    def test_missing_cv_profile_returns_zero_counts(self):
        _insert_scoreable()
        with patch("evaluator.runner.load_active_profile", side_effect=ValueError("No CV")):
            result = run()
        assert result == {"jobs_scored": 0}

    def test_normal_scoring_sets_score_keeps_new_status(self):
        _insert_scoreable()
        with _patched_run():
            result = run()
        assert result["jobs_scored"] == 1
        jobs = job_repository.search()
        assert jobs[0]["score"] == 7.5
        assert jobs[0]["status"] == "new"

    def test_build_system_prompt_called_once_for_entire_batch(self):
        _insert_scoreable(url="https://a.com/1")
        _insert_scoreable(company="Beta", url="https://a.com/2")
        with patch("evaluator.runner.load_active_profile", return_value="fake profile"):
            with patch("evaluator.runner.build_system_prompt", return_value="fake") as mock_prompt:
                with patch("evaluator.runner.score_job", return_value=_good_score()):
                    run()
        mock_prompt.assert_called_once()

    def test_already_scored_job_not_rescored(self):
        job_id = _insert_scoreable()
        job_repository.update_score(job_id, 6.0, "Already scored")
        with _patched_run() as mock_score:
            run()
        mock_score.assert_not_called()

    def test_score_reason_stored_in_db(self):
        _insert_scoreable()
        with _patched_run(_good_score(score_reason="Symfony match, remote OK")):
            run()
        assert "Symfony match" in job_repository.search()[0]["score_reason"]

    def test_multiple_jobs_all_scored(self):
        _insert_scoreable(url="https://a.com/1")
        _insert_scoreable(company="Beta", url="https://a.com/2")
        with _patched_run(side_effect=[_good_score(), _good_score(score=5.0)]):
            result = run()
        assert result["jobs_scored"] == 2

    def test_scoring_failure_leaves_job_unscored_for_retry(self):
        _insert_scoreable()
        error_result = {"score": None, "score_reason": "API error: timeout"}
        with _patched_run(side_effect=[error_result]):
            result = run()
        assert result["jobs_scored"] == 0
        job = job_repository.search()[0]
        assert job["score"] is None

    def test_low_score_auto_rejects_job(self):
        _insert_scoreable()
        with _patched_run(_good_score(score=0.5, score_reason="No PHP, wrong field entirely")):
            result = run()
        assert result["jobs_scored"] == 1
        assert result["jobs_auto_rejected"] == 1
        job = job_repository.search()[0]
        assert job["status"] == "auto_rejected"
        assert job["score"] == 0.5

    def test_score_at_threshold_is_auto_rejected(self):
        _insert_scoreable()
        with _patched_run(_good_score(score=1.0)):
            run()
        assert job_repository.search()[0]["status"] == "auto_rejected"

    def test_score_just_above_threshold_stays_new(self):
        _insert_scoreable()
        with _patched_run(_good_score(score=1.5)):
            result = run()
        assert result["jobs_auto_rejected"] == 0
        assert job_repository.search()[0]["status"] == "new"

    def test_divergence_cases_passed_to_build_system_prompt(self):
        _insert_scoreable()
        fake_cases = [{"divergence_type": "false_positive", "listwise_rank": 2, "title": "X", "rejection_reason": "Y"}]
        with patch("evaluator.runner.load_active_profile", return_value="fake profile"):
            with patch("evaluator.runner.divergence_cases", return_value=fake_cases):
                with patch("evaluator.runner.build_system_prompt", return_value="fake") as mock_prompt:
                    with patch("evaluator.runner.score_job", return_value=_good_score()):
                        run()
        assert mock_prompt.call_args.kwargs["divergence_cases"] == fake_cases

    def test_divergence_cases_capped_at_limit(self):
        _insert_scoreable()
        many_cases = [
            {"divergence_type": "false_positive", "listwise_rank": i, "title": f"Job {i}", "rejection_reason": "x"}
            for i in range(50)
        ]
        with patch("evaluator.runner.load_active_profile", return_value="fake profile"):
            with patch("evaluator.runner.divergence_cases", return_value=many_cases):
                with patch("evaluator.runner.build_system_prompt", return_value="fake") as mock_prompt:
                    with patch("evaluator.runner.score_job", return_value=_good_score()):
                        run()
        assert len(mock_prompt.call_args.kwargs["divergence_cases"]) == 10
