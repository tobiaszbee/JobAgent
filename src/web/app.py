import os
import sys
import json
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, render_template, jsonify, request
from flask_sock import Sock
from src.db.repositories import job_repository as jobs
from src.db.repositories import criteria_repository as criteria
from src.db.repositories import application_repository as applications

app = Flask(__name__, template_folder="templates", static_folder="static")
sock = Sock(app)

agent_process = None


@app.route("/")
def dashboard():
    stats = jobs.get_stats()
    return render_template("dashboard.html", stats=stats)


@app.route("/api/jobs")
def api_jobs():
    status    = request.args.get("status", "all")
    min_score = request.args.get("min_score", type=float)
    query     = request.args.get("search", "")
    return jsonify(jobs.search(status=status, min_score=min_score, query=query or None))


@app.route("/api/jobs/<job_id>/status", methods=["POST"])
def update_status(job_id):
    data = request.get_json()
    new_status = data.get("status")

    if new_status not in ("reviewed", "applied", "rejected", "new"):
        return jsonify({"error": "Invalid status"}), 400

    jobs.update_status(job_id, new_status)

    if new_status == "applied":
        applications.insert(job_id)

    return jsonify({"ok": True, "status": new_status})


@app.route("/api/stats")
def api_stats():
    return jsonify(jobs.get_stats())


@app.route("/api/criteria")
def api_criteria():
    return jsonify(criteria.get_all())


@app.route("/api/criteria", methods=["POST"])
def api_criteria_add():
    data  = request.get_json()
    type_ = data.get("type")
    value = data.get("value", "").strip()
    if not type_ or not value:
        return jsonify({"error": "type and value required"}), 400
    criteria.insert(type_, value)
    return jsonify({"ok": True})


@app.route("/api/criteria/<int:id>/toggle", methods=["POST"])
def api_criteria_toggle(id):
    data = request.get_json()
    criteria.toggle(id, data.get("active", True))
    return jsonify({"ok": True})


@app.route("/api/criteria/<int:id>", methods=["DELETE"])
def api_criteria_delete(id):
    criteria.delete(id)
    return jsonify({"ok": True})


@app.route("/api/agent/status")
def agent_status():
    global agent_process
    running = agent_process is not None and agent_process.poll() is None
    return jsonify({"running": running})


@sock.route("/ws/agent")
def agent_ws(ws):
    global agent_process

    if agent_process is not None and agent_process.poll() is None:
        ws.send("ERROR: Agent is already running.\n")
        return

    data = ws.receive()
    try:
        params = json.loads(data)
    except Exception:
        params = {}

    days      = int(params.get("days", 7))
    max_jobs  = params.get("max_jobs")
    max_jobs  = int(max_jobs) if max_jobs else None
    titles    = params.get("titles", [])
    locations = params.get("locations", [])

    cmd = [sys.executable, "-u", os.path.join(ROOT, "src", "agent.py"),
           "--days", str(days)]
    if max_jobs:
        cmd += ["--max-jobs", str(max_jobs)]
    if titles:
        cmd += ["--titles"] + titles
    if locations:
        cmd += ["--locations"] + locations

    ws.send(f"Starting agent: days={days}, max_jobs={max_jobs or 'unlimited'}\n")
    ws.send(f"Titles: {', '.join(titles) if titles else 'all active'}\n")
    ws.send(f"Locations: {', '.join(locations) if locations else 'all active'}\n")

    agent_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=ROOT
    )

    try:
        for line in agent_process.stdout:
            try:
                ws.send(line)
            except Exception:
                break
    except Exception:
        pass

    agent_process.wait()
    try:
        ws.send("\n__DONE__\n")
    except Exception:
        pass


if __name__ == "__main__":
    print("Starting Job Agent Dashboard...")
    print("Open: http://localhost:5000")
    app.run(debug=False, port=5000)
