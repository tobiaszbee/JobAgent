from flask import Blueprint, jsonify, request
from db.repositories import job_repository

bp = Blueprint("jobs", __name__)


@bp.get("/api/jobs")
def list_jobs():
    status    = request.args.get("status", "all")
    min_score = request.args.get("min_score", type=float)
    query     = request.args.get("search", "").strip() or None
    source    = request.args.get("source", "").strip() or None
    return jsonify(job_repository.search(status=status, min_score=min_score, query=query, source=source))


@bp.post("/api/jobs/<job_id>/status")
def update_status(job_id):
    data = request.get_json()
    new_status = data.get("status")
    if new_status not in ("new", "reviewed", "applied", "rejected"):
        return jsonify({"error": "Invalid status"}), 400
    job_repository.update_status(job_id, new_status)
    return jsonify({"ok": True, "status": new_status})


@bp.get("/api/stats")
def stats():
    return jsonify(job_repository.get_stats())


@bp.get("/api/jobs/missing-descriptions")
def missing_descriptions():
    jobs = job_repository.get_missing_descriptions()
    return jsonify({"count": len(jobs)})
