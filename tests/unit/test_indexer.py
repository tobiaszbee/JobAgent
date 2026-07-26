import json
import pytest
from unittest.mock import MagicMock, patch

from db.connection import get_connection
from embeddings.client import VoyageClient
from embeddings.indexer import _embed_with_retry, _job_to_text, build_ideal_vector, index_jobs, score_by_similarity


def _insert_job(job_id: str, status: str = "new") -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, title, company, location, url, description, source, status) VALUES (?,?,?,?,?,?,?,?)",
        (job_id, "Dev", "Corp", "Remote", f"https://a.com/{job_id}", "desc", "linkedin", status),
    )
    conn.commit()
    conn.close()


def _insert_embedding(job_id: str, vec: list[float]) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO job_embeddings (job_id, embedding, model) VALUES (?,?,?)",
        (job_id, json.dumps(vec), "voyage-3-large"),
    )
    conn.commit()
    conn.close()


class TestJobToText:
    def test_includes_title_and_company(self):
        job = {"title": "Senior Dev", "company": "Acme", "location": None, "description": None}
        text = _job_to_text(job)
        assert "Senior Dev at Acme" in text

    def test_includes_location_when_present(self):
        job = {"title": "Dev", "company": "Co", "location": "Warsaw", "description": None}
        assert "Warsaw" in _job_to_text(job)

    def test_omits_location_when_absent(self):
        job = {"title": "Dev", "company": "Co", "location": None, "description": None}
        assert "Location:" not in _job_to_text(job)

    def test_includes_description(self):
        job = {"title": "Dev", "company": "Co", "location": None, "description": "Python expert"}
        assert "Python expert" in _job_to_text(job)

    def test_truncates_description_at_2000_chars(self):
        long_desc = "x" * 3000
        job = {"title": "Dev", "company": "Co", "location": None, "description": long_desc}
        text = _job_to_text(job)
        assert "x" * 2000 in text
        assert "x" * 2001 not in text

    def test_strips_linkedin_junk_before_embedding(self):
        # Regression guard: _job_to_text used to slice job["description"] raw, so
        # LinkedIn's page-chrome junk (footer links, "people also viewed") could land
        # inside the embedded text for short postings. It must go through
        # build_excerpt() so junk is stripped first, same as every other consumer.
        job = {
            "title": "Dev", "company": "Co", "location": None, "source": "linkedin",
            "description": "Real job content here.\nSet alert for similar jobs\nUnrelated junk.",
        }
        text = _job_to_text(job)
        assert "Real job content here." in text
        assert "Unrelated junk" not in text

    def test_non_linkedin_source_passes_description_through_unchanged(self):
        job = {"title": "Dev", "company": "Co", "location": None, "source": "remotive", "description": "Clean text"}
        assert "Clean text" in _job_to_text(job)


class TestBuildIdealVector:
    def test_returns_none_when_no_applied_jobs(self):
        assert build_ideal_vector() is None

    def test_returns_centroid_when_no_rejected_jobs(self):
        _insert_job("j1", status="applied")
        _insert_embedding("j1", [1.0, 0.0])

        result = build_ideal_vector()
        assert result is not None
        assert abs(result[0] - 1.0) < 1e-9
        assert abs(result[1] - 0.0) < 1e-9

    def test_centroid_of_two_applied_jobs(self):
        _insert_job("j1", status="applied")
        _insert_job("j2", status="applied")
        _insert_embedding("j1", [2.0, 4.0])
        _insert_embedding("j2", [4.0, 0.0])

        result = build_ideal_vector()
        assert result is not None
        assert abs(result[0] - 3.0) < 1e-9
        assert abs(result[1] - 2.0) < 1e-9

    def test_subtracts_rejected_centroid_with_weight(self):
        # applied centroid: [2.0, 0.0]
        # rejected centroid: [0.0, 1.0]
        # ideal: [2.0 - 0.3*0.0, 0.0 - 0.3*1.0] = [2.0, -0.3]
        _insert_job("ja", status="applied")
        _insert_embedding("ja", [2.0, 0.0])
        _insert_job("jr", status="rejected")
        _insert_embedding("jr", [0.0, 1.0])

        result = build_ideal_vector()
        assert result is not None
        assert abs(result[0] - 2.0) < 1e-9
        assert abs(result[1] - (-0.3)) < 1e-9

    def test_ignores_jobs_without_embeddings(self):
        _insert_job("j1", status="applied")  # no embedding → skipped
        # query returns zero rows → no applied embeddings → None
        assert build_ideal_vector() is None

    def test_no_applied_jobs_no_profile_returns_none(self):
        assert build_ideal_vector(candidate_profile=None) is None
        assert build_ideal_vector(candidate_profile="") is None

    @patch("embeddings.indexer._get_client")
    def test_falls_back_to_embedding_candidate_profile_when_no_applied_jobs(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.embed.return_value = [[0.7, 0.7]]
        mock_get_client.return_value = mock_client

        result = build_ideal_vector(candidate_profile="CANDIDATE:\n- Senior PHP Developer")

        assert result == [0.7, 0.7]
        mock_client.embed.assert_called_once_with(["CANDIDATE:\n- Senior PHP Developer"], input_type="query")

    def test_applied_history_takes_priority_over_profile_fallback(self):
        _insert_job("j1", status="applied")
        _insert_embedding("j1", [1.0, 0.0])

        result = build_ideal_vector(candidate_profile="CANDIDATE:\n- Senior PHP Developer")

        assert result is not None
        assert abs(result[0] - 1.0) < 1e-9


class TestEmbedWithRetry:
    def test_returns_on_first_success(self):
        mock_client = MagicMock()
        mock_client.embed.return_value = [[0.1, 0.2]]
        result = _embed_with_retry(mock_client, ["text"])
        assert result == [[0.1, 0.2]]
        assert mock_client.embed.call_count == 1

    @patch("embeddings.indexer.time.sleep")
    def test_retries_on_rate_limit_error(self, mock_sleep):
        mock_client = MagicMock()
        mock_client.embed.side_effect = [
            Exception("rate limit exceeded"),
            [[0.5, 0.6]],
        ]
        result = _embed_with_retry(mock_client, ["text"])
        assert result == [[0.5, 0.6]]
        assert mock_client.embed.call_count == 2
        mock_sleep.assert_called_once()

    @patch("embeddings.indexer.time.sleep")
    def test_retries_on_429_error(self, mock_sleep):
        mock_client = MagicMock()
        mock_client.embed.side_effect = [
            Exception("HTTP 429 too many requests"),
            [[0.3]],
        ]
        result = _embed_with_retry(mock_client, ["text"])
        assert result == [[0.3]]

    def test_raises_immediately_on_non_rate_limit_error(self):
        mock_client = MagicMock()
        mock_client.embed.side_effect = ValueError("invalid input")
        with pytest.raises(ValueError, match="invalid input"):
            _embed_with_retry(mock_client, ["text"])
        assert mock_client.embed.call_count == 1


class TestIndexJobs:
    def test_returns_zero_for_empty_list(self):
        assert index_jobs([]) == 0

    @patch("embeddings.indexer.time.sleep")
    @patch("embeddings.indexer._get_client")
    def test_indexes_jobs_and_returns_count(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
        mock_get_client.return_value = mock_client

        _insert_job("j1")
        _insert_job("j2")
        jobs = [
            {"id": "j1", "title": "Dev A", "company": "Corp", "location": None, "description": "Python"},
            {"id": "j2", "title": "Dev B", "company": "Corp", "location": None, "description": "Java"},
        ]

        count = index_jobs(jobs)
        assert count == 2

    @patch("embeddings.indexer.time.sleep")
    @patch("embeddings.indexer._get_client")
    def test_stores_embeddings_in_db(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.embed.return_value = [[0.9, 0.1]]
        mock_get_client.return_value = mock_client

        _insert_job("j1")
        jobs = [{"id": "j1", "title": "Dev", "company": "Corp", "location": None, "description": "desc"}]
        index_jobs(jobs)

        conn = get_connection()
        row = conn.execute("SELECT embedding FROM job_embeddings WHERE job_id = ?", ("j1",)).fetchone()
        conn.close()
        assert row is not None
        assert json.loads(row["embedding"]) == [0.9, 0.1]


class TestScoreBySimilarity:
    def test_empty_job_ids_returns_empty_dict(self):
        assert score_by_similarity([], [1.0, 0.0]) == {}

    def test_empty_ideal_returns_empty_dict(self):
        assert score_by_similarity(["j1"], []) == {}

    def test_computes_cosine_similarity(self):
        _insert_job("j1")
        _insert_embedding("j1", [1.0, 0.0])

        ideal = [1.0, 0.0]

        with patch("embeddings.indexer._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.cosine_similarity = VoyageClient.cosine_similarity
            mock_get.return_value = mock_client

            scores = score_by_similarity(["j1"], ideal)

        assert "j1" in scores
        assert abs(scores["j1"] - 1.0) < 1e-9

    def test_missing_embedding_not_in_result(self):
        _insert_job("j1")  # no embedding in DB

        with patch("embeddings.indexer._get_client") as mock_get:
            mock_get.return_value = MagicMock()
            scores = score_by_similarity(["j1"], [1.0, 0.0])

        assert scores == {}
