from flask import Blueprint, jsonify
from db.repositories import excluded_search_queries_repository

bp = Blueprint("search_queries", __name__)


@bp.get("/api/search-queries/excluded")
def list_excluded():
    return jsonify(excluded_search_queries_repository.get_all())


@bp.post("/api/search-queries/excluded/<int:id>/reinstate")
def reinstate_excluded(id):
    excluded_search_queries_repository.reinstate(id)
    return jsonify({"ok": True})
