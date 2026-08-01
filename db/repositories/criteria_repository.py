import api_client

VALID_TYPES = {"title", "location", "required", "preferred", "rejected", "search_query"}


def get_all() -> list[dict]:
    return api_client.get("/api/criteria").json()


def get_active(type_: str) -> list[str]:
    return get_active_dict().get({
        "search_query": "search_queries", "title": "titles", "location": "locations",
        "required": "required", "preferred": "preferred", "rejected": "rejected",
    }[type_], [])


def get_active_dict() -> dict:
    return api_client.get("/api/criteria/active").json()


def insert(type_: str, value: str) -> None:
    if type_ not in VALID_TYPES:
        raise ValueError(f"Invalid criteria type: {type_!r}. Must be one of {VALID_TYPES}")
    api_client.post("/api/criteria", json={"type": type_, "value": value})


def toggle(id_: int, is_active: bool) -> None:
    api_client.patch(f"/api/criteria/{id_}", json={"is_active": is_active})


def delete(id_: int) -> None:
    api_client.delete(f"/api/criteria/{id_}")


def delete_by_type(type_: str) -> int:
    return api_client.delete(f"/api/criteria/by-type/{type_}").json()["deleted"]
