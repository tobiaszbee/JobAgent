from unittest.mock import MagicMock, patch

from ranker.reranker import rerank_jobs


def _job(id="j1", title="Developer", company="Corp", description="Python dev role"):
    return {"id": id, "title": title, "company": company, "description": description}


class TestRerankJobs:
    def test_empty_input_returns_empty_list(self):
        assert rerank_jobs([], "python") == []

    def test_returns_jobs_sorted_by_rerank_score(self):
        jobs = [_job("j1", "Dev A"), _job("j2", "Dev B"), _job("j3", "Dev C")]
        rerank_results = [
            {"index": 2, "score": 0.95},
            {"index": 0, "score": 0.80},
            {"index": 1, "score": 0.60},
        ]
        with patch("ranker.reranker._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.rerank.return_value = rerank_results
            mock_get.return_value = mock_client

            result = rerank_jobs(jobs, "python developer", top_k=3)

        assert len(result) == 3
        assert result[0]["id"] == "j3"
        assert result[1]["id"] == "j1"
        assert result[2]["id"] == "j2"
        assert result[0]["rerank_score"] == 0.95

    def test_attaches_rerank_score_to_each_job(self):
        jobs = [_job("j1")]
        with patch("ranker.reranker._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.rerank.return_value = [{"index": 0, "score": 0.77}]
            mock_get.return_value = mock_client

            result = rerank_jobs(jobs, "query")

        assert result[0]["rerank_score"] == 0.77

    def test_truncates_description_to_1000_chars(self):
        long_desc = "x" * 2000
        jobs = [_job("j1", description=long_desc)]
        captured = []

        def capture_rerank(query, documents, top_k):
            captured.extend(documents)
            return [{"index": 0, "score": 0.5}]

        with patch("ranker.reranker._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.rerank.side_effect = capture_rerank
            mock_get.return_value = mock_client

            rerank_jobs(jobs, "query")

        assert len(captured) == 1
        assert "x" * 1001 not in captured[0]

    def test_uses_default_query_when_none_given(self):
        jobs = [_job("j1")]
        used_query = []

        def capture(query, documents, top_k):
            used_query.append(query)
            return [{"index": 0, "score": 0.5}]

        with patch("ranker.reranker._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.rerank.side_effect = capture
            mock_get.return_value = mock_client

            rerank_jobs(jobs, query=None)

        assert used_query[0] == "software engineer developer"

    def test_fallback_on_api_error_preserves_original_order(self):
        jobs = [_job("j1"), _job("j2"), _job("j3")]
        for j in jobs:
            j["_embedding_score"] = 0.0

        with patch("ranker.reranker._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.rerank.side_effect = Exception("Voyage down")
            mock_get.return_value = mock_client

            result = rerank_jobs(jobs, "python", top_k=3)

        assert [r["id"] for r in result] == ["j1", "j2", "j3"]

    def test_fallback_sets_rerank_score_from_embedding_score(self):
        jobs = [_job("j1")]
        jobs[0]["_embedding_score"] = 0.42

        with patch("ranker.reranker._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.rerank.side_effect = Exception("fail")
            mock_get.return_value = mock_client

            result = rerank_jobs(jobs, "query")

        assert result[0]["rerank_score"] == 0.42

    def test_respects_top_k_limit(self):
        jobs = [_job(f"j{i}") for i in range(5)]
        rerank_results = [{"index": i, "score": 1.0 - i * 0.1} for i in range(5)]

        with patch("ranker.reranker._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.rerank.return_value = rerank_results[:2]
            mock_get.return_value = mock_client

            result = rerank_jobs(jobs, "query", top_k=2)

        assert len(result) == 2
