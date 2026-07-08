from flask import Blueprint, jsonify, request
from db.repositories import job_repository, cv_repository

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
    rejection_reason = data.get("rejection_reason") if new_status == "rejected" else None
    job_repository.update_status(job_id, new_status, rejection_reason)
    return jsonify({"ok": True, "status": new_status})


@bp.get("/api/stats")
def stats():
    data = job_repository.get_stats()
    data["has_cv"] = cv_repository.get_active() is not None
    from db.repositories import usage_repository
    data["usage"] = usage_repository.get_summary()
    return jsonify(data)


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


@bp.delete("/api/jobs")
def delete_jobs():
    statuses  = request.args.getlist("status")
    date_from = request.args.get("date_from") or None
    date_to   = request.args.get("date_to") or None
    if not statuses:
        return jsonify({"error": "At least one status required"}), 400
    n = job_repository.delete_by_filter(statuses, date_from, date_to)
    return jsonify({"deleted": n})
