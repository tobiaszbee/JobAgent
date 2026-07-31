import api_client
from db.repositories import job_repository
from config import WOULD_APPLY


def precision_at_k(k: int = 10) -> dict:
    """
    Precision@K: among the top-K ranked jobs that the user has already decided on,
    what fraction were positive decisions (applied)?

    "reviewed" is deliberately excluded — per the dashboard's own status meaning
    (jobs read but not decided on), it isn't a decision at all, so counting it as a
    positive would credit the ranking for jobs the user never actually validated.
    """
    rows = api_client.get("/api/jobs/ranked", params={
        "status": ["applied", "rejected", "auto_rejected"],
    }).json()[:k]

    if not rows:
        return {"precision_at_k": None, "k": k, "n_evaluated": 0, "n_positive": 0}

    positive = sum(1 for r in rows if r["status"] == "applied")
    return {
        "precision_at_k": round(positive / len(rows), 3),
        "k": k,
        "n_evaluated": len(rows),
        "n_positive": positive,
    }


def divergence_cases() -> list[dict]:
    """
    Cases where the model ranking diverged from user decision:
    - rank ≤ 5 + rejected  → false positive (model overrated it)
    - rank ≥ 16 + applied  → false negative (model underrated it)
    These are the highest-value training signals for preference distillation.
    """
    rows = api_client.get("/api/jobs/ranked", params={"status": ["applied", "rejected"]}).json()

    cases = []
    for row in rows:
        rank = row["listwise_rank"]
        if rank <= 5 and row["status"] == "rejected":
            cases.append({
                **row,
                "divergence_type": "false_positive",
                "label": f"Ranked #{rank} but rejected",
            })
        elif rank >= 16 and row["status"] == "applied":
            cases.append({
                **row,
                "divergence_type": "false_negative",
                "label": f"Applied despite rank #{rank}",
            })

    return cases


def total_ranked() -> int:
    return api_client.get("/api/jobs/ranked-count").json()["count"]


def eval_report() -> dict:
    """Full evaluation report combining precision@K, divergence cases, and the
    would-apply flag's precision (the gate for the phase-2 auto-apply decision)."""
    p5  = precision_at_k(5)
    p10 = precision_at_k(10)
    return {
        "precision_at_5":  p5["precision_at_k"],
        "precision_at_10": p10["precision_at_k"],
        "n_evaluated_5":   p5["n_evaluated"],
        "n_evaluated_10":  p10["n_evaluated"],
        "divergence_cases": divergence_cases(),
        "total_ranked": total_ranked(),
        "would_apply": job_repository.get_would_apply_stats(),
        "would_apply_score_floor": WOULD_APPLY["score_floor"],
    }
