from flask import Blueprint, jsonify
from collector.sources import available

bp = Blueprint("sources", __name__)


@bp.get("/api/sources")
def list_sources():
    return jsonify(available())
