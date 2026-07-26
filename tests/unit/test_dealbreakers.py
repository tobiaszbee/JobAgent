import json
from unittest.mock import patch

from evaluator.dealbreakers import apply_dealbreaker_filter


def _job(job_id="job1", structured=None, **overrides):
    job = {
        "id": job_id, "title": "PHP Developer", "company": "Acme",
        "structured_data": json.dumps(structured) if structured is not None else None,
    }
    job.update(overrides)
    return job


def _prefs(**overrides):
    base = {"salary_min": None, "salary_currency": None, "work_mode": []}
    base.update(overrides)
    return base


class TestNoActivePreferences:
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active", return_value=None)
    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    def test_passes_everything_through(self, mock_update, mock_prefs):
        jobs = [_job("a"), _job("b")]
        surviving, stats = apply_dealbreaker_filter(jobs)
        assert surviving == jobs
        assert stats == {"checked": 2, "auto_rejected": 0}
        mock_update.assert_not_called()


class TestSalaryFloor:
    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_rejects_below_minimum_yearly(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        job = _job(structured={"salary_max": 100000, "salary_currency": "PLN", "salary_period": "yearly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == []
        assert stats["auto_rejected"] == 1
        mock_update.assert_called_once()
        assert mock_update.call_args[0][3] == "auto_rejected"
        assert "salary_max 100000" in mock_update.call_args[0][2]

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_passes_at_or_above_minimum_yearly(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        job = _job(structured={"salary_max": 200000, "salary_currency": "PLN", "salary_period": "yearly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        assert stats["auto_rejected"] == 0
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_monthly_rate_normalized_before_comparison(self, mock_prefs, mock_update):
        # 20000 PLN/month = 240000 PLN/year, comfortably above a 150000/year floor.
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        job = _job(structured={"salary_max": 20000, "salary_currency": "PLN", "salary_period": "monthly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_low_monthly_rate_still_rejected_after_normalization(self, mock_prefs, mock_update):
        # 5000 PLN/month = 60000 PLN/year, below a 150000/year floor.
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        job = _job(structured={"salary_max": 5000, "salary_currency": "PLN", "salary_period": "monthly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == []
        assert stats["auto_rejected"] == 1

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_hourly_b2b_rate_not_mistaken_for_a_starvation_salary(self, mock_prefs, mock_update):
        # Regression test for the real bug: "100-145 PLN/h" B2B rate must never be
        # compared directly against an annual floor as if it were annual pay.
        # 145 PLN/h * 168h/month * 12 = 292,320 PLN/year — well above 150000/year.
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        job = _job(structured={"salary_max": 145, "salary_currency": "PLN", "salary_period": "hourly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_low_hourly_rate_still_rejected_after_normalization(self, mock_prefs, mock_update):
        # 20 PLN/h * 2016h/year = 40,320 PLN/year — below a 150000/year floor.
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        job = _job(structured={"salary_max": 20, "salary_currency": "PLN", "salary_period": "hourly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == []
        assert stats["auto_rejected"] == 1

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_skips_when_pay_period_unknown(self, mock_prefs, mock_update):
        # Old/un-migrated structured_data without salary_period — never guess a
        # basis, skip rather than risk a false rejection.
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        job = _job(structured={"salary_max": 100, "salary_currency": "PLN"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_skips_when_job_has_no_structured_data(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(salary_min=15000, salary_currency="PLN")
        job = _job(structured=None)
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_skips_when_job_salary_currency_missing(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(salary_min=15000, salary_currency="PLN")
        job = _job(structured={"salary_max": 5000, "salary_currency": None, "salary_period": "monthly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_skips_on_currency_mismatch(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(salary_min=15000, salary_currency="PLN")
        job = _job(structured={"salary_max": 3000, "salary_currency": "EUR", "salary_period": "monthly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_no_candidate_salary_min_never_filters(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(salary_min=None, salary_currency=None)
        job = _job(structured={"salary_max": 1, "salary_currency": "PLN", "salary_period": "yearly"})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()


class TestRemoteOnlyMismatch:
    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_rejects_hybrid_job_for_remote_only_candidate(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(work_mode=["remote"])
        job = _job(structured={"remote": False, "hybrid": True})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == []
        assert stats["auto_rejected"] == 1
        assert "remote-only" in mock_update.call_args[0][2]

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_rejects_onsite_job_for_remote_only_candidate(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(work_mode=["remote"])
        job = _job(structured={"remote": False, "hybrid": False})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == []
        assert stats["auto_rejected"] == 1

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_passes_remote_job_for_remote_only_candidate(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(work_mode=["remote"])
        job = _job(structured={"remote": True, "hybrid": False})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_rejects_job_offering_both_remote_and_hybrid(self, mock_prefs, mock_update):
        # hybrid=True disqualifies a remote-only candidate even when remote=True is
        # also set — confirmed with the candidate: hybrid means occasional required
        # office days regardless of what else the posting advertises.
        mock_prefs.return_value = _prefs(work_mode=["remote"])
        job = _job(structured={"remote": True, "hybrid": True})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == []
        assert stats["auto_rejected"] == 1

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_rejects_hybrid_only_job_when_remote_unknown(self, mock_prefs, mock_update):
        # remote wasn't extracted (None), but hybrid=True is confirmed — still a
        # violation, since we only know about the hybrid requirement, not full remote.
        mock_prefs.return_value = _prefs(work_mode=["remote"])
        job = _job(structured={"remote": None, "hybrid": True})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == []
        assert stats["auto_rejected"] == 1

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_skips_when_no_structured_work_mode_data(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(work_mode=["remote"])
        job = _job(structured={})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()

    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_hybrid_candidate_never_filtered_by_work_mode_rule(self, mock_prefs, mock_update):
        # work_mode includes hybrid, not remote-only — rule only applies to exactly ["remote"].
        mock_prefs.return_value = _prefs(work_mode=["remote", "hybrid"])
        job = _job(structured={"remote": False, "hybrid": False})
        surviving, stats = apply_dealbreaker_filter([job])
        assert surviving == [job]
        mock_update.assert_not_called()


class TestMultipleJobs:
    @patch("evaluator.dealbreakers.job_repository.update_score_and_status")
    @patch("evaluator.dealbreakers.candidate_preferences_repository.get_active")
    def test_mixed_batch_filters_only_violators(self, mock_prefs, mock_update):
        mock_prefs.return_value = _prefs(salary_min=150000, salary_currency="PLN")
        good = _job("good", structured={"salary_max": 200000, "salary_currency": "PLN", "salary_period": "yearly"})
        bad = _job("bad", structured={"salary_max": 50000, "salary_currency": "PLN", "salary_period": "yearly"})
        surviving, stats = apply_dealbreaker_filter([good, bad])
        assert surviving == [good]
        assert stats == {"checked": 2, "auto_rejected": 1}


class TestAnnualize:
    def test_yearly_returned_unchanged(self):
        from evaluator.dealbreakers import _annualize
        assert _annualize(200000, "yearly") == 200000

    def test_monthly_multiplied_by_12(self):
        from evaluator.dealbreakers import _annualize
        assert _annualize(20000, "monthly") == 240000

    def test_hourly_multiplied_by_2016(self):
        from evaluator.dealbreakers import _annualize
        assert _annualize(100, "hourly") == 201600

    def test_unknown_period_returns_none(self):
        from evaluator.dealbreakers import _annualize
        assert _annualize(100, None) is None
        assert _annualize(100, "fortnightly") is None
