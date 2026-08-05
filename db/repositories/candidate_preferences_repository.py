import api_client


def insert(cv_profile_id: int | None, fields: dict | None = None) -> int:
    try:
        resp = api_client.post("/api/candidate-preferences", json={
            "cv_profile_id": cv_profile_id, "fields": fields or {},
        })
    except api_client.ApiError as e:
        if e.status_code == 400:
            raise ValueError(e.detail) from e
        raise
    return resp.json()["id"]


def get_active() -> dict | None:
    try:
        return api_client.get("/api/candidate-preferences/active").json()
    except api_client.ApiError as e:
        if e.status_code == 404:
            return None
        raise


def list_all() -> list[dict]:
    return api_client.get("/api/candidate-preferences").json()


def set_active(id_: int) -> None:
    api_client.post(f"/api/candidate-preferences/{id_}/activate")


def update(id_: int, fields: dict) -> None:
    if not fields:
        return
    try:
        api_client.patch(f"/api/candidate-preferences/{id_}", json={"fields": fields})
    except api_client.ApiError as e:
        if e.status_code == 400:
            raise ValueError(e.detail) from e
        raise


def delete(id_: int) -> None:
    api_client.delete(f"/api/candidate-preferences/{id_}")
