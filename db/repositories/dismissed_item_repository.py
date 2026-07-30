import api_client


def insert(job_id: str, item_type: str, item_text: str, reason: str) -> None:
    api_client.post(f"/api/jobs/{job_id}/dismiss-item", json={
        "item_type": item_type, "item_text": item_text, "reason": reason,
    })


def get_for_job(job_id: str) -> list[dict]:
    return api_client.get(f"/api/jobs/{job_id}/dismissed-items").json()["items"]


def get_recent(limit: int = 50) -> list[dict]:
    """Most recent dismissals across all jobs, for the distillation prompt."""
    return api_client.get("/api/dismissed-items/recent", params={"limit": limit}).json()


def count_all() -> int:
    return api_client.get("/api/dismissed-items/count").json()["count"]
