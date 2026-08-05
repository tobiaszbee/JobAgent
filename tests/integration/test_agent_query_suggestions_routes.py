import itertools

import config
from db.repositories import excluded_search_queries_repository, job_repository

_counter = itertools.count()


def _terminal_jobs(query, rejected=0, applied=0, reviewed=0, source="linkedin"):
    for _ in range(rejected):
        n = next(_counter)
        job_id = job_repository.insert(f"Title {n}", f"Co {n}", "PL", f"https://a.com/{query}/{n}", source, search_query=query)
        job_repository.update_status(job_id, "rejected")
    for _ in range(applied):
        n = next(_counter)
        job_id = job_repository.insert(f"Title {n}", f"Co {n}", "PL", f"https://a.com/{query}/{n}", source, search_query=query)
        job_repository.update_status(job_id, "applied")
    for _ in range(reviewed):
        n = next(_counter)
        job_id = job_repository.insert(f"Title {n}", f"Co {n}", "PL", f"https://a.com/{query}/{n}", source, search_query=query)
        job_repository.update_status(job_id, "reviewed")


class TestAgentQuerySuggestionsGet:
    def test_returns_empty_when_nothing_qualifies(self, flask_client):
        resp = flask_client.get("/api/agent/query-suggestions")

        assert resp.status_code == 200
        assert resp.json == {"suggestions": []}

    def test_returns_qualifying_query(self, flask_client, monkeypatch):
        monkeypatch.setitem(config.QUERY_PRUNING, "min_terminal_sample", 10)
        monkeypatch.setitem(config.QUERY_PRUNING, "suggestion_reject_rate_threshold", 0.7)
        _terminal_jobs("Senior Developer", rejected=17, reviewed=2)  # 89.5% reject, 0 applied

        resp = flask_client.get("/api/agent/query-suggestions")

        assert resp.status_code == 200
        queries = [s["search_query"] for s in resp.json["suggestions"]]
        assert queries == ["Senior Developer"]


class TestAgentQuerySuggestionsApply:
    def test_excludes_the_checked_queries(self, flask_client):
        resp = flask_client.post("/api/agent/query-suggestions/apply", json={"queries": ["Senior Developer", "Lead Developer"]})

        assert resp.status_code == 200
        assert resp.json == {"excluded": ["Senior Developer", "Lead Developer"]}
        excluded = excluded_search_queries_repository.get_excluded("linkedin")
        assert set(excluded) == {"Senior Developer", "Lead Developer"}

    def test_empty_list_excludes_nothing(self, flask_client):
        resp = flask_client.post("/api/agent/query-suggestions/apply", json={"queries": []})

        assert resp.status_code == 200
        assert resp.json == {"excluded": []}
        assert excluded_search_queries_repository.get_excluded("linkedin") == {}

    def test_missing_body_excludes_nothing(self, flask_client):
        resp = flask_client.post("/api/agent/query-suggestions/apply", json={})

        assert resp.status_code == 200
        assert resp.json == {"excluded": []}

    def test_applied_exclusion_removes_it_from_future_suggestions(self, flask_client, monkeypatch):
        monkeypatch.setitem(config.QUERY_PRUNING, "min_terminal_sample", 10)
        monkeypatch.setitem(config.QUERY_PRUNING, "suggestion_reject_rate_threshold", 0.7)
        _terminal_jobs("Senior Developer", rejected=17, reviewed=2)

        flask_client.post("/api/agent/query-suggestions/apply", json={"queries": ["Senior Developer"]})
        resp = flask_client.get("/api/agent/query-suggestions")

        assert resp.json == {"suggestions": []}
