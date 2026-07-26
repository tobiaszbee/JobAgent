from flask import Blueprint, jsonify, request
from db.repositories import job_repository, cv_repository, dismissed_item_repository

# Public-safe routes only — browsing jobs and changing status. Registered in both
# "local" and "web" deployment modes (see web/app.py). Anything that mutates beyond
# a status change (bulk delete, dismissing a score item) or leaks internal counts
# lives in jobs_admin.bp instead, which "web" mode never registers — this is a
# route-level allowlist, not a blueprint-level toggle, so a public JobAgentWeb can
# never reach them even by guessing the URL.
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


@bp.get("/api/jobs/<job_id>/dismissed-items")
def get_dismissed_items(job_id):
    return jsonify({"items": dismissed_item_repository.get_for_job(job_id)})
