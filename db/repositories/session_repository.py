import api_client


def start() -> int:
    return api_client.post("/api/sessions").json()["id"]


def finish(session_id: int, jobs_found: int, jobs_scored: int, status: str = "done") -> None:
    api_client.patch(f"/api/sessions/{session_id}/finish", json={
        "jobs_found": jobs_found, "jobs_scored": jobs_scored, "status": status,
    })


def cancel_active() -> None:
    api_client.post("/api/sessions/cancel-active")


def has_active_run() -> bool:
    """True if a session started within the last 6 hours is still running."""
    return api_client.get("/api/sessions/has-active").json()["active"]


def get_last_finished_at() -> str | None:
    return api_client.get("/api/sessions/last-finished").json()["finished_at"]


def mark_collected(session_id: int) -> None:
    api_client.post(f"/api/sessions/{session_id}/mark-collected")


def get_last_collected_at() -> str | None:
    return api_client.get("/api/sessions/last-collected").json()["collected_at"]


def get_latest() -> dict | None:
    return api_client.get("/api/sessions/latest").json()["session"]
