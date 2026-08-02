import json
import uuid
import pytest
from unittest.mock import MagicMock, patch

import math

import api_client
from db.repositories import job_repository
from embeddings.indexer import (
    _embed_with_retry, _job_to_text, _l2_normalize, build_ideal_vector, index_jobs, score_by_similarity,
)


def _insert_job(status: str = "new") -> str:
    job_id = job_repository.insert(
        title="Dev", company="Corp", location="Remote",
        url=f"https://a.com/{uuid.uuid4().hex}", source="linkedin", description="desc",
    )
    if status != "new":
        job_repository.update_status(job_id, status)
    return job_id


def _insert_embedding(job_id: str, vec: list[float]) -> None:
    api_client.post("/api/embeddings", json={
        "items": [{"job_id": job_id, "embedding": vec, "model": "voyage-3-large"}],
    })


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


class TestL2Normalize:
    def test_scales_to_unit_length(self):
        result = _l2_normalize([3.0, 4.0])
        assert abs(result[0] - 0.6) < 1e-9
        assert abs(result[1] - 0.8) < 1e-9

    def test_already_unit_vector_unchanged(self):
        result = _l2_normalize([1.0, 0.0])
        assert result == [1.0, 0.0]

    def test_zero_vector_returned_unchanged_not_divided_by_zero(self):
        assert _l2_normalize([0.0, 0.0]) == [0.0, 0.0]

    def test_direction_preserved_scale_invariant(self):
        a = _l2_normalize([2.0, 0.0])
        b = _l2_normalize([10.0, 0.0])
        assert a == b


class TestBuildIdealVector:
    def test_returns_none_when_no_applied_jobs(self):
        assert build_ideal_vector() is None

    def test_returns_centroid_when_no_rejected_jobs(self):
        j1 = _insert_job(status="applied")
        _insert_embedding(j1, [1.0, 0.0])

        result = build_ideal_vector()
        assert result is not None
        assert abs(result[0] - 1.0) < 1e-9
        assert abs(result[1] - 0.0) < 1e-9

    def test_centroid_of_two_applied_jobs_is_l2_normalized(self):
        # raw mean: [3.0, 2.0], norm = sqrt(13) — the centroid is unit-normalized
        # before being returned so its direction (not an arbitrary raw magnitude
        # driven by how many/how similar the applied jobs are) is what downstream
        # cosine similarity actually compares against.
        j1 = _insert_job(status="applied")
        j2 = _insert_job(status="applied")
        _insert_embedding(j1, [2.0, 4.0])
        _insert_embedding(j2, [4.0, 0.0])

        result = build_ideal_vector()
        assert result is not None
        norm = math.sqrt(13)
        assert abs(result[0] - 3.0 / norm) < 1e-9
        assert abs(result[1] - 2.0 / norm) < 1e-9
        assert abs(math.sqrt(result[0] ** 2 + result[1] ** 2) - 1.0) < 1e-9

    def test_subtracts_rejected_centroid_with_weight(self):
        # applied centroid (raw [2.0, 0.0], already unit length after normalizing): [1.0, 0.0]
        # rejected centroid (raw [0.0, 1.0], already unit length): [0.0, 1.0]
        # ideal: [1.0 - 0.3*0.0, 0.0 - 0.3*1.0] = [1.0, -0.3]
        ja = _insert_job(status="applied")
        _insert_embedding(ja, [2.0, 0.0])
        jr = _insert_job(status="rejected")
        _insert_embedding(jr, [0.0, 1.0])

        result = build_ideal_vector()
        assert result is not None
        assert abs(result[0] - 1.0) < 1e-9
        assert abs(result[1] - (-0.3)) < 1e-9

    def test_rejected_weight_unaffected_by_raw_centroid_magnitude(self):
        # Regression for the audit's exact finding: a tightly clustered rejected
        # set (large raw centroid magnitude, little internal cancellation)
        # pushed the pre-fix ideal vector much harder than a diffuse one (small
        # raw magnitude from vectors partially canceling out), even though both
        # represent "the candidate rejected some jobs" equally. A rejected
        # vector 5x the raw magnitude but identical direction must now produce
        # the exact same ideal vector.
        ja = _insert_job(status="applied")
        _insert_embedding(ja, [1.0, 0.0])
        jr = _insert_job(status="rejected")
        _insert_embedding(jr, [0.0, 5.0])  # same direction as [0.0, 1.0], 5x the raw magnitude

        result = build_ideal_vector()
        assert result is not None
        assert abs(result[0] - 1.0) < 1e-9
        assert abs(result[1] - (-0.3)) < 1e-9

    def test_ignores_jobs_without_embeddings(self):
        _insert_job(status="applied")  # no embedding → skipped
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
        j1 = _insert_job(status="applied")
        _insert_embedding(j1, [1.0, 0.0])

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

        j1 = _insert_job()
        j2 = _insert_job()
        jobs = [
            {"id": j1, "title": "Dev A", "company": "Corp", "location": None, "description": "Python"},
            {"id": j2, "title": "Dev B", "company": "Corp", "location": None, "description": "Java"},
        ]

        count = index_jobs(jobs)
        assert count == 2

    @patch("embeddings.indexer.time.sleep")
    @patch("embeddings.indexer._get_client")
    def test_stores_embeddings_in_db(self, mock_get_client, mock_sleep):
        mock_client = MagicMock()
        mock_client.embed.return_value = [[0.9, 0.1]]
        mock_get_client.return_value = mock_client

        j1 = _insert_job()
        jobs = [{"id": j1, "title": "Dev", "company": "Corp", "location": None, "description": "desc"}]
        index_jobs(jobs)

        vectors = api_client.post("/api/embeddings/vectors", json={"job_ids": [j1]}).json()
        assert vectors[j1] == [0.9, 0.1]


class TestScoreBySimilarity:
    def test_empty_job_ids_returns_empty_dict(self):
        assert score_by_similarity([], [1.0, 0.0]) == {}

    def test_empty_ideal_returns_empty_dict(self):
        assert score_by_similarity(["j1"], []) == {}

    def test_computes_cosine_similarity(self):
        # Computed server-side now (JobAgentWeb's /api/embeddings/similarity) rather
        # than fetched-then-scored locally — no VoyageClient involved at all here.
        j1 = _insert_job()
        _insert_embedding(j1, [1.0, 0.0])

        scores = score_by_similarity([j1], [1.0, 0.0])

        assert j1 in scores
        assert abs(scores[j1] - 1.0) < 1e-9

    def test_missing_embedding_not_in_result(self):
        j1 = _insert_job()  # no embedding
        scores = score_by_similarity([j1], [1.0, 0.0])
        assert scores == {}
