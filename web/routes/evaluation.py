from flask import Blueprint, jsonify

from evaluation.harness import eval_report

bp = Blueprint("evaluation", __name__)


@bp.get("/api/eval/report")
def report():
    return jsonify(eval_report())
