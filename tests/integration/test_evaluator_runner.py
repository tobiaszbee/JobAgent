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
        "matched_required": ["PHP"],
        "matched_preferred": [],
        "dealbreakers_found": [],
        **overrides,
    }


def _noop(*args, **kwargs):
    pass


class TestEvaluatorRunner:
    def test_no_jobs_returns_zero_counts(self):
        result = run(log=_noop)
        assert result == {"jobs_scored": 0, "auto_rejected": 0}

    def test_job_without_description_is_skipped(self):
        job_repository.insert("No desc", "Co", "PL", "https://a.com/1", "linkedin")
        with patch("evaluator.runner.score_job") as mock_score:
            run(log=_noop)
        mock_score.assert_not_called()

    def test_normal_scoring_sets_score_keeps_new_status(self):
        job_id = _insert_scoreable()
        with patch("evaluator.runner.score_job", return_value=_good_score()):
            with patch("evaluator.runner.build_system_prompt", return_value="fake"):
                result = run(log=_noop)
        assert result["jobs_scored"] == 1
        assert result["auto_rejected"] == 0
        jobs = job_repository.search()
        assert jobs[0]["score"] == 7.5
        assert jobs[0]["status"] == "new"

    def test_dealbreaker_sets_auto_rejected_status(self):
        job_id = _insert_scoreable()
        with patch("evaluator.runner.score_job",
                   return_value=_good_score(dealbreakers_found=["On-site only"], score=0.0)):
            with patch("evaluator.runner.build_system_prompt", return_value="fake"):
                result = run(log=_noop)
        assert result["auto_rejected"] == 1
        jobs = job_repository.search()
        assert jobs[0]["status"] == "auto_rejected"
        assert jobs[0]["score"] == 0.0

    def test_build_system_prompt_called_once_for_entire_batch(self):
        _insert_scoreable(url="https://a.com/1")
        _insert_scoreable(company="Beta", url="https://a.com/2")
        with patch("evaluator.runner.score_job", return_value=_good_score()):
            with patch("evaluator.runner.build_system_prompt", return_value="fake") as mock_prompt:
                run(log=_noop)
        mock_prompt.assert_called_once()

    def test_already_scored_job_not_rescored(self):
        job_id = _insert_scoreable()
        job_repository.update_score(job_id, 6.0, "Already scored")
        with patch("evaluator.runner.score_job") as mock_score:
            run(log=_noop)
        mock_score.assert_not_called()

    def test_score_reason_stored_in_db(self):
        job_id = _insert_scoreable()
        with patch("evaluator.runner.score_job",
                   return_value=_good_score(score_reason="Symfony match, remote OK")):
            with patch("evaluator.runner.build_system_prompt", return_value="fake"):
                run(log=_noop)
        jobs = job_repository.search()
        assert "Symfony match" in jobs[0]["score_reason"]

    def test_mixed_batch_counts_correctly(self):
        _insert_scoreable(url="https://a.com/1")
        _insert_scoreable(company="Beta", url="https://a.com/2")

        scores = [
            _good_score(),
            _good_score(dealbreakers_found=["On-site only"], score=0.0),
        ]
        with patch("evaluator.runner.score_job", side_effect=scores):
            with patch("evaluator.runner.build_system_prompt", return_value="fake"):
                result = run(log=_noop)

        assert result["jobs_scored"] == 2
        assert result["auto_rejected"] == 1
