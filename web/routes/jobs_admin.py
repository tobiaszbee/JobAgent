from flask import Blueprint, jsonify, request
from db.repositories import job_repository, dismissed_item_repository

# Bulk delete, score-item dismissal, and internal counts, split from jobs.bp for organization.
bp = Blueprint("jobs_admin", __name__)


@bp.get("/api/jobs/missing-descriptions")
def missing_descriptions():
    jobs = job_repository.get_missing_descriptions()
    return jsonify({"count": len(jobs)})


@bp.get("/api/jobs/count")
def count_jobs():
    statuses  = request.args.getlist("status")
    date_from = request.args.get("date_from") or None
    date_to   = request.args.get("date_to") or None
    return jsonify({"count": job_repository.count_by_filter(statuses, date_from, date_to)})


@bp.post("/api/jobs/<job_id>/dismiss-item")
def dismiss_item(job_id):
    data = request.get_json() or {}
    item_type = data.get("item_type")
    item_text = (data.get("item_text") or "").strip()
    reason = (data.get("reason") or "").strip()
    if item_type not in ("pro", "con") or not item_text or not reason:
        return jsonify({"error": "item_type ('pro' or 'con'), item_text, and reason are required"}), 400
    dismissed_item_repository.insert(job_id, item_type, item_text, reason)
    return jsonify({"ok": True})


@bp.delete("/api/jobs")
def delete_jobs():
    statuses  = request.args.getlist("status")
    date_from = request.args.get("date_from") or None
    date_to   = request.args.get("date_to") or None
    if not statuses:
        return jsonify({"error": "At least one status required"}), 400
    n = job_repository.delete_by_filter(statuses, date_from, date_to)
    return jsonify({"deleted": n})
