from flask import Blueprint, jsonify, request
from db.repositories import job_repository, cv_repository, dismissed_item_repository

# Browsing + status changes only. Bulk delete, score-item dismissal, and internal
# counts live in jobs_admin.bp instead — see that module.
bp = Blueprint("jobs", __name__)

# Safety net, not a normal-use limit — a status/search/source-filtered view under
# regular triage is dozens to a few hundred jobs. This only engages during a real
# pileup (e.g. the pool grows unattended for months), and the dashboard shows a
# visible banner rather than silently dropping jobs off the end.
_LIST_SAFETY_CAP = 2000


@bp.get("/api/jobs")
def list_jobs():
    status    = request.args.get("status", "all")
    min_score = request.args.get("min_score", type=float)
    query     = request.args.get("search", "").strip() or None
    source    = request.args.get("source", "").strip() or None
    results = job_repository.search(
        status=status, min_score=min_score, query=query, source=source, limit=_LIST_SAFETY_CAP,
    )
    resp = jsonify(results)
    resp.headers["X-Jobs-Truncated"] = "true" if len(results) >= _LIST_SAFETY_CAP else "false"
    return resp


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
