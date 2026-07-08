from config import MODEL_COSTS
from db.connection import get_connection


def _calc_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    rates = MODEL_COSTS.get(model, (0.0, 0.0))
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


def log_usage(model: str, module: str, input_tokens: int, output_tokens: int = 0) -> None:
    cost = _calc_cost(model, input_tokens, output_tokens)
    try:
        conn = get_connection()
        conn.execute(
            "INSERT INTO usage_log (model, module, input_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?)",
            (model, module, input_tokens, output_tokens, cost),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Never block the main flow


def log_anthropic(response, module: str, model: str) -> None:
    """Log usage from an Anthropic messages.create() response."""
    try:
        log_usage(model, module, response.usage.input_tokens, response.usage.output_tokens)
    except Exception:
        pass


def log_voyage_embed(total_tokens: int) -> None:
    log_usage("voyage-3-large", "embed", total_tokens)


def log_voyage_rerank(n_docs: int) -> None:
    """Voyage rerank pricing: $0.05 per 1K queries. Store n_docs as input_tokens."""
    log_usage("rerank-2", "rerank", n_docs)


def get_summary() -> dict:
    try:
        conn = get_connection()
        today = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(input_tokens+output_tokens),0) "
            "FROM usage_log WHERE date(created_at) = date('now')"
        ).fetchone()
        total = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(input_tokens+output_tokens),0) "
            "FROM usage_log"
        ).fetchone()
        conn.close()
        return {
            "today_cost_usd":  round(today[0], 4),
            "today_tokens":    today[1],
            "total_cost_usd":  round(total[0], 4),
            "total_tokens":    total[1],
        }
    except Exception:
        return {"today_cost_usd": 0, "today_tokens": 0, "total_cost_usd": 0, "total_tokens": 0}
