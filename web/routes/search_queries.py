from flask import Blueprint, jsonify

import api_client
from db.repositories import excluded_search_queries_repository

bp = Blueprint("search_queries", __name__)


@bp.get("/api/search-queries/excluded")
def list_excluded():
    return jsonify(excluded_search_queries_repository.get_all())


@bp.post("/api/search-queries/excluded/<int:id>/reinstate")
def reinstate_excluded(id):
    try:
        excluded_search_queries_repository.reinstate(id)
    except api_client.ApiError as e:
        return jsonify({"error": e.detail}), e.status_code
    return jsonify({"ok": True})
