import json
import os
import subprocess
import sys
from flask import Blueprint
from flask_sock import Sock

bp = Blueprint("runner", __name__)
sock = Sock()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_agent_process: subprocess.Popen | None = None


def init_sock(app):
    sock.init_app(app)


@bp.get("/api/agent/status")
def agent_status():
    running = _agent_process is not None and _agent_process.poll() is None
    return {"running": running}


def _run_script(ws, script_path: str, extra_args: list[str] = []) -> int:
    """Run a script as a subprocess, stream output to ws. Returns exit code."""
    global _agent_process
    cmd = [sys.executable, "-u", script_path] + extra_args
    _agent_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=ROOT,
    )
    for line in _agent_process.stdout:
        try:
            ws.send(line)
        except Exception:
            _agent_process.terminate()
            return -1
    _agent_process.wait()
    return _agent_process.returncode


@sock.route("/ws/agent")
def agent_ws(ws):
    global _agent_process

    if _agent_process is not None and _agent_process.poll() is None:
        ws.send("ERROR: Agent is already running.\n")
        return

    raw = ws.receive()
    try:
        params = json.loads(raw)
    except Exception:
        params = {}

    days      = int(params.get("days", 7))
    max_jobs  = params.get("max_jobs")
    max_jobs  = int(max_jobs) if max_jobs else None
    titles    = params.get("titles") or []
    locations = params.get("locations") or []

    collector_args = ["--days", str(days)]
    if max_jobs:
        collector_args += ["--max-jobs", str(max_jobs)]
    if titles:
        collector_args += ["--titles"] + titles
    if locations:
        collector_args += ["--locations"] + locations

    ws.send(f"=== COLLECTOR (days={days}, max_jobs={max_jobs or 'unlimited'}) ===\n")
    rc = _run_script(ws, os.path.join(ROOT, "collector", "runner.py"), collector_args)

    if rc != 0:
        ws.send(f"\nCollector failed (exit code {rc}). Skipping evaluator.\n")
    else:
        ws.send("\n=== EVALUATOR ===\n")
        _run_script(ws, os.path.join(ROOT, "evaluator", "runner.py"))

    _agent_process = None
    try:
        ws.send("\n__DONE__\n")
    except Exception:
        pass
