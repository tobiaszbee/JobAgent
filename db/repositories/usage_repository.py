import json
from datetime import datetime, timezone

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


def log_voyage_rerank(total_tokens: int) -> None:
    """Voyage rerank pricing is per token processed (query + documents), $0.05/1M tokens."""
    log_usage("rerank-2", "rerank", total_tokens)


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
            "today_cost_usd":   round(today[0], 4),
            "today_tokens":     today[1],
            "total_cost_usd":   round(total[0], 4),
            "total_tokens":     total[1],
            "cost_per_100_usd": get_cost_per_100(),
        }
    except Exception:
        return {"today_cost_usd": 0, "today_tokens": 0, "total_cost_usd": 0, "total_tokens": 0, "cost_per_100_usd": None}


def record_run_summary(run_label: str, started_at: str) -> None:
    """Snapshot everything logged to usage_log since `started_at` (a pipeline run's
    start time) into a durable, per-run record — token/cost breakdown per model, how
    many jobs got scored, and this run's own cost-per-100. Called once at the end of
    each pipeline run (web/routes/runner.py). Deliberately never touches or depends on
    the `jobs` table, so deleting jobs later can't corrupt historical cost figures."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT model, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
        "SUM(cost_usd) AS cost_usd FROM usage_log WHERE created_at >= ? GROUP BY model",
        (started_at,),
    ).fetchall()
    if not rows:
        conn.close()
        return

    breakdown = {
        r["model"]: {
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd": round(r["cost_usd"], 6),
        }
        for r in rows
    }
    total_cost = sum(r["cost_usd"] for r in rows)

    jobs_evaluated = conn.execute(
        "SELECT COUNT(*) FROM usage_log WHERE created_at >= ? AND module = 'scorer'",
        (started_at,),
    ).fetchone()[0]
    cost_per_100 = round(total_cost / jobs_evaluated * 100, 4) if jobs_evaluated else None

    conn.execute(
        "INSERT INTO cost_summaries (run_label, started_at, jobs_evaluated, total_cost_usd, cost_per_100_usd, breakdown) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_label, started_at, jobs_evaluated, round(total_cost, 6), cost_per_100, json.dumps(breakdown)),
    )
    conn.commit()
    conn.close()


def get_cost_per_100() -> float | None:
    """Rolling average cost-per-100-jobs-scored across every recorded run — never a
    function of how many jobs currently exist in the `jobs` table."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(total_cost_usd),0), COALESCE(SUM(jobs_evaluated),0) "
        "FROM cost_summaries WHERE jobs_evaluated > 0"
    ).fetchone()
    conn.close()
    total_cost, jobs_evaluated = row[0], row[1]
    return round(total_cost / jobs_evaluated * 100, 4) if jobs_evaluated else None


def now_iso() -> str:
    """SQLite CURRENT_TIMESTAMP-compatible timestamp (UTC, matching usage_log's
    default), for capturing a run's start time to pass into record_run_summary()."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
