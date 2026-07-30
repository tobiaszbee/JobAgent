import api_client


def insert(filename: str, raw_text: str, parsed: dict) -> int:
    """Insert a new CV profile, making it the active one. Returns the new row id."""
    resp = api_client.post("/api/cv-profiles", json={"filename": filename, "raw_text": raw_text, "parsed": parsed})
    return resp.json()["id"]


def get_active() -> dict | None:
    try:
        return api_client.get("/api/cv-profiles/active").json()
    except api_client.ApiError as e:
        if e.status_code == 404:
            return None
        raise


def list_all() -> list[dict]:
    return api_client.get("/api/cv-profiles").json()


def set_active(id_: int) -> None:
    api_client.post(f"/api/cv-profiles/{id_}/activate")
