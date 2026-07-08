from flask import Blueprint, jsonify

bp = Blueprint("ranking", __name__)


@bp.get("/api/ranking/status")
def status():
    from db.repositories import job_repository
    jobs = job_repository.get_jobs_for_ranking(limit=1)
    return jsonify({"pending": len(jobs)})
