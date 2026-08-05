from flask import Blueprint, jsonify

from db.repositories import preference_repository, usage_repository
from preference_agent import runner as preference_runner
from preference_agent.profile import render_signals

bp = Blueprint("preferences", __name__)


@bp.get("/api/preferences")
def get_preferences():
    profile = preference_repository.get_latest()
    if not profile:
        return jsonify({"profile": None})
    signals = profile.get("signals", [])
    return jsonify({
        "profile": {
            "signals": signals,
            "content": render_signals(signals) if signals else profile["content"],
            "applied_count": profile["applied_count"],
            "rejected_count": profile["rejected_count"],
            "updated_at": profile["updated_at"],
        }
    })


@bp.post("/api/preferences/distill")
def distill():
    # A manual distill runs an Opus call outside any tracked pipeline run — same
    # started_at -> record_run_summary envelope web/routes/runner.py's
    # _run_pipeline_ws uses, so this cost stops silently missing from
    # cost_summaries. Recorded even on failure (the try/finally): a failed
    # distill can still have billed a real Anthropic call before erroring.
    started_at = usage_repository.now_iso()
    try:
        result = preference_runner.run()
    finally:
        usage_repository.record_run_summary("distill_preferences", started_at)
    if not result["ok"]:
        return jsonify(result), 400
    return jsonify(result)
