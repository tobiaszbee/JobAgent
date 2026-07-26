from unittest.mock import MagicMock, patch

from langdetect.language import Language

from collector.language_filter import apply_language_filter


def _job(job_id="job1", title="PHP Developer", description="We need a senior PHP developer with Symfony experience for our team."):
    return {"id": job_id, "title": title, "company": "Acme", "description": description}


def _prefs(languages):
    return {"languages": languages}


class TestNoConfiguredLanguages:
    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active", return_value=None)
    def test_no_active_preferences_skips_everything(self, mock_prefs, mock_jr):
        result = apply_language_filter()
        assert result == {"checked": 0, "auto_rejected": 0}
        mock_jr.get_new.assert_not_called()

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    def test_empty_languages_list_skips_everything(self, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([])
        result = apply_language_filter()
        assert result == {"checked": 0, "auto_rejected": 0}
        mock_jr.get_new.assert_not_called()

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    def test_unrecognized_language_name_ignored(self, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "klingon", "level": "Native"}])
        result = apply_language_filter()
        assert result == {"checked": 0, "auto_rejected": 0}
        mock_jr.get_new.assert_not_called()


class TestDetectionBehavior:
    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    @patch("collector.language_filter.detect_langs")
    def test_matching_language_passes(self, mock_detect, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        mock_jr.get_new.return_value = [_job()]
        mock_detect.return_value = [Language("en", 0.99)]

        result = apply_language_filter()
        assert result == {"checked": 1, "auto_rejected": 0}
        mock_jr.update_score_and_status.assert_not_called()

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    @patch("collector.language_filter.detect_langs")
    def test_mismatched_language_rejects(self, mock_detect, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        mock_jr.get_new.return_value = [_job()]
        mock_detect.return_value = [Language("de", 0.95)]

        result = apply_language_filter()
        assert result == {"checked": 1, "auto_rejected": 1}
        mock_jr.update_score_and_status.assert_called_once()
        args = mock_jr.update_score_and_status.call_args[0]
        assert args[3] == "auto_rejected"
        assert "de" in args[2]

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    @patch("collector.language_filter.detect_langs")
    def test_any_candidate_language_matching_passes(self, mock_detect, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([
            {"language": "english", "level": "C1"},
            {"language": "polish", "level": "Native"},
        ])
        mock_jr.get_new.return_value = [_job()]
        mock_detect.return_value = [Language("pl", 0.9)]

        result = apply_language_filter()
        assert result == {"checked": 1, "auto_rejected": 0}
        mock_jr.update_score_and_status.assert_not_called()

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    @patch("collector.language_filter.detect_langs")
    def test_mixed_language_posting_passes_if_either_matches(self, mock_detect, mock_prefs, mock_jr):
        # A posting detect_langs finds plausible in both German and English —
        # candidate only speaks English, should still pass (overlap exists).
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        mock_jr.get_new.return_value = [_job()]
        mock_detect.return_value = [Language("de", 0.55), Language("en", 0.4)]

        result = apply_language_filter()
        assert result == {"checked": 1, "auto_rejected": 0}
        mock_jr.update_score_and_status.assert_not_called()

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    @patch("collector.language_filter.detect_langs")
    def test_detection_failure_skips_gracefully(self, mock_detect, mock_prefs, mock_jr):
        from langdetect.lang_detect_exception import LangDetectException
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        mock_jr.get_new.return_value = [_job()]
        mock_detect.side_effect = LangDetectException(1, "no features")

        result = apply_language_filter()
        assert result == {"checked": 1, "auto_rejected": 0}
        mock_jr.update_score_and_status.assert_not_called()

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    @patch("collector.language_filter.detect_langs")
    def test_short_text_skipped_without_calling_detector(self, mock_detect, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        mock_jr.get_new.return_value = [_job(title="Dev", description="")]

        result = apply_language_filter()
        assert result == {"checked": 1, "auto_rejected": 0}
        mock_detect.assert_not_called()

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    @patch("collector.language_filter.detect_langs")
    def test_mixed_batch_only_rejects_violators(self, mock_detect, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        good = _job("good")
        bad = _job("bad")
        mock_jr.get_new.return_value = [good, bad]
        mock_detect.side_effect = [[Language("en", 0.9)], [Language("pl", 0.9)]]

        result = apply_language_filter()
        assert result == {"checked": 2, "auto_rejected": 1}
        mock_jr.update_score_and_status.assert_called_once()
        call_args = mock_jr.update_score_and_status.call_args[0]
        assert call_args[0] == "bad"
        assert call_args[3] == "auto_rejected"


class TestRealDetection:
    """A handful of cases against the real langdetect library, not mocked —
    guards against the library's API or default behavior changing under us."""

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    def test_real_english_text_passes_for_english_candidate(self, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        mock_jr.get_new.return_value = [_job(description=(
            "We are looking for a senior backend engineer with strong experience "
            "in PHP and Symfony to join our growing product team."
        ))]
        result = apply_language_filter()
        assert result["auto_rejected"] == 0

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    def test_real_polish_text_rejected_for_english_only_candidate(self, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "english", "level": "C1"}])
        mock_jr.get_new.return_value = [_job(description=(
            "Poszukujemy doświadczonego programisty backend ze znajomością PHP "
            "oraz frameworka Symfony do naszego zespołu produktowego."
        ))]
        result = apply_language_filter()
        assert result["auto_rejected"] == 1

    @patch("collector.language_filter.job_repository")
    @patch("collector.language_filter.candidate_preferences_repository.get_active")
    def test_real_polish_text_passes_for_polish_candidate(self, mock_prefs, mock_jr):
        mock_prefs.return_value = _prefs([{"language": "polish", "level": "Native"}])
        mock_jr.get_new.return_value = [_job(description=(
            "Poszukujemy doświadczonego programisty backend ze znajomością PHP "
            "oraz frameworka Symfony do naszego zespołu produktowego."
        ))]
        result = apply_language_filter()
        assert result["auto_rejected"] == 0
