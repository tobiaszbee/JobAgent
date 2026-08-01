import logging

from flask import Blueprint, jsonify, request

from db.repositories import criteria_repository
from query_expansion.runner import suggest_queries

logger = logging.getLogger(__name__)

bp = Blueprint("query_expansion", __name__)


@bp.get("/api/query-expansion/suggest")
def suggest():
    result = suggest_queries()
    return jsonify(result)


@bp.post("/api/query-expansion/apply")
def apply():
    data = request.get_json() or {}
    queries = data.get("queries", [])
    if not queries:
        return jsonify({"error": "No queries provided"}), 400

    added = 0
    for q in queries:
        q = q.strip()
        if q:
            try:
                criteria_repository.insert("search_query", q)
                added += 1
            except Exception:
                logger.warning(f"Failed to add suggested search query {q!r}", exc_info=True)

    return jsonify({"ok": True, "added": added})
