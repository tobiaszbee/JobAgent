import api_client


def exclude(source: str, search_query: str, reason: str) -> None:
    """Idempotent — re-excluding an already-excluded query updates its reason
    instead of erroring, so a re-run with fresher stats keeps the log current."""
    api_client.post("/api/excluded-search-queries", json={
        "source": source, "search_query": search_query, "reason": reason,
    })


def get_excluded(source: str) -> dict[str, str]:
    """search_query -> reason, for filtering a source's query list before collection."""
    return api_client.get("/api/excluded-search-queries/by-source", params={"source": source}).json()


def get_all() -> list[dict]:
    return api_client.get("/api/excluded-search-queries").json()


def reinstate(id_: int) -> None:
    api_client.post(f"/api/excluded-search-queries/{id_}/reinstate")
