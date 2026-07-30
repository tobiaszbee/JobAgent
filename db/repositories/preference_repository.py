import api_client


def get_latest() -> dict | None:
    return api_client.get("/api/preference-profile").json()["profile"]


def save(signals: list[dict], applied_count: int, rejected_count: int, dismissed_count: int = 0) -> None:
    api_client.post("/api/preference-profile", json={
        "signals": signals, "applied_count": applied_count,
        "rejected_count": rejected_count, "dismissed_count": dismissed_count,
    })
