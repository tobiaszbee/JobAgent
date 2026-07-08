from flask import Blueprint, jsonify, request
from db.repositories import criteria_repository

bp = Blueprint("criteria", __name__)


@bp.get("/api/criteria")
def list_criteria():
    return jsonify(criteria_repository.get_all())


@bp.post("/api/criteria")
def add_criterion():
    data  = request.get_json()
    type_ = data.get("type", "").strip()
    value = data.get("value", "").strip()
    if not type_ or not value:
        return jsonify({"error": "type and value are required"}), 400
    try:
        criteria_repository.insert(type_, value)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@bp.post("/api/criteria/<int:id>/toggle")
def toggle_criterion(id):
    data = request.get_json()
    criteria_repository.toggle(id, data.get("active", True))
    return jsonify({"ok": True})


@bp.delete("/api/criteria/<int:id>")
def delete_criterion(id):
    criteria_repository.delete(id)
    return jsonify({"ok": True})
