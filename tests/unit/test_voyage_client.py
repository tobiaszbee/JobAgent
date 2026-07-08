from unittest.mock import MagicMock, patch

from embeddings.client import VoyageClient


class TestCosineSimilarity:
    def test_orthogonal_vectors_return_zero(self):
        assert VoyageClient.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_identical_vectors_return_one(self):
        v = [1.0, 2.0, 3.0]
        assert abs(VoyageClient.cosine_similarity(v, v) - 1.0) < 1e-9

    def test_opposite_vectors_return_minus_one(self):
        assert abs(VoyageClient.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-9

    def test_zero_vector_returns_zero(self):
        assert VoyageClient.cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_known_values(self):
        # [1,1] vs [1,0]: dot=1, |a|=sqrt(2), |b|=1 → 1/sqrt(2) ≈ 0.707
        result = VoyageClient.cosine_similarity([1.0, 1.0], [1.0, 0.0])
        assert abs(result - (1.0 / 2**0.5)) < 1e-9


class TestEmbed:
    @patch("embeddings.client.VoyageClient.__init__", return_value=None)
    def test_returns_embeddings_from_voyageai(self, _mock_init):
        client = VoyageClient()
        mock_inner = MagicMock()
        mock_result = MagicMock()
        mock_result.embeddings = [[0.1, 0.2, 0.3]]
        mock_result.total_tokens = 10
        mock_inner.embed.return_value = mock_result
        client._client = mock_inner

        result = client.embed(["hello world"])
        assert result == [[0.1, 0.2, 0.3]]
        mock_inner.embed.assert_called_once()

    @patch("embeddings.client.VoyageClient.__init__", return_value=None)
    def test_embed_passes_input_type(self, _mock_init):
        client = VoyageClient()
        client._client = MagicMock()
        client._client.embed.return_value = MagicMock(embeddings=[[0.5]], total_tokens=5)

        client.embed(["text"], input_type="query")
        call_kwargs = client._client.embed.call_args
        assert call_kwargs is not None


class TestRerank:
    @patch("embeddings.client.VoyageClient.__init__", return_value=None)
    def test_returns_index_score_pairs(self, _mock_init):
        client = VoyageClient()
        r1 = MagicMock(index=2, relevance_score=0.95)
        r2 = MagicMock(index=0, relevance_score=0.70)
        mock_result = MagicMock()
        mock_result.results = [r1, r2]
        client._client = MagicMock()
        client._client.rerank.return_value = mock_result

        result = client.rerank("query", ["doc0", "doc1", "doc2"], top_k=2)
        assert result == [{"index": 2, "score": 0.95}, {"index": 0, "score": 0.70}]

    @patch("embeddings.client.VoyageClient.__init__", return_value=None)
    def test_rerank_calls_voyageai_with_correct_args(self, _mock_init):
        client = VoyageClient()
        client._client = MagicMock()
        client._client.rerank.return_value = MagicMock(results=[])

        client.rerank("python developer", ["doc1", "doc2"], top_k=1)
        client._client.rerank.assert_called_once()
