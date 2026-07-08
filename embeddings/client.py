import math
import logging

from config import VOYAGE_API_KEY, VOYAGE_EMBED_MODEL, VOYAGE_RERANK_MODEL

logger = logging.getLogger(__name__)


def _require_voyage():
    if not VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY not set — add it to .env to use embedding/rerank features.")
    try:
        import voyageai  # noqa: F401
    except ImportError:
        raise RuntimeError("voyageai package not installed. Run: pip install voyageai")


class VoyageClient:
    def __init__(self):
        _require_voyage()
        import voyageai
        self._client = voyageai.Client(api_key=VOYAGE_API_KEY)

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        """Embed a list of texts. input_type: 'document' for indexing, 'query' for retrieval."""
        result = self._client.embed(texts, model=VOYAGE_EMBED_MODEL, input_type=input_type)
        try:
            from db.repositories.usage_repository import log_voyage_embed
            log_voyage_embed(getattr(result, "total_tokens", len(texts) * 512))
        except Exception:
            pass
        return result.embeddings

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[dict]:
        """Cross-encoder rerank. Returns list of {index, score} sorted by score desc."""
        result = self._client.rerank(query, documents, model=VOYAGE_RERANK_MODEL, top_k=top_k)
        return [{"index": r.index, "score": r.relevance_score} for r in result.results]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
