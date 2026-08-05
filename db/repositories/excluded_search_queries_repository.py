import api_client


def exclude(source: str, search_query: str, reason: str) -> None:
    api_client.post("/api/excluded-search-queries", json={
        "source": source, "search_query": search_query, "reason": reason,
    })


def get_excluded(source: str) -> dict[str, str]:
    return api_client.get("/api/excluded-search-queries/by-source", params={"source": source}).json()


def get_all() -> list[dict]:
    return api_client.get("/api/excluded-search-queries").json()


def reinstate(id_: int) -> None:
    api_client.post(f"/api/excluded-search-queries/{id_}/reinstate")
