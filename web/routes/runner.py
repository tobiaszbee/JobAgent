import json
import os
import subprocess
import sys
import threading
from flask import Blueprint
from flask_sock import Sock

bp = Blueprint("runner", __name__)
sock = Sock()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_FILE = os.path.join(ROOT, "data", "logs", "current_run.log")

_agent_process: subprocess.Popen | None = None
_lock = threading.Lock()


def init_sock(app):
    sock.init_app(app)


def _is_run_active() -> bool:
    if _agent_process is not None and _agent_process.poll() is None:
        return True
    from db.repositories import session_repository
    return session_repository.has_active_run()


@bp.get("/api/agent/status")
def agent_status():
    return {"running": _is_run_active()}


@bp.post("/api/agent/stop")
def agent_stop():
    global _agent_process
    if _agent_process is not None and _agent_process.poll() is None:
        _agent_process.terminate()
        from db.repositories import session_repository
        session_repository.cancel_active()
        return {"ok": True}
    return {"ok": False, "reason": "not running"}


@bp.get("/api/agent/logs")
def agent_logs():
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return {"lines": [l.rstrip("\n") for l in lines[-200:]]}
    except FileNotFoundError:
        return {"lines": []}


def _run_script(ws, script_path: str, extra_args: list[str] = [], _log_file=None) -> int:
    """Run a script as a subprocess, stream output to ws and optionally to log file."""
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
        if _log_file:
            _log_file.write(line)
            _log_file.flush()
        try:
            ws.send(line)
        except Exception:
            _agent_process.terminate()
            return -1
    _agent_process.wait()
    return _agent_process.returncode


def _open_log():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    return open(LOG_FILE, "w", encoding="utf-8")


@sock.route("/ws/agent")
def agent_ws(ws):
    global _agent_process

    with _lock:
        if _is_run_active():
            ws.send("ERROR: Agent is already running.\n")
            return

    raw = ws.receive()
    try:
        params = json.loads(raw)
    except Exception:
        params = {}

    try:
        days = int(params.get("days", 1))
    except (ValueError, TypeError):
        ws.send("ERROR: Invalid parameter 'days' — must be an integer.\n")
        return

    max_jobs_raw = params.get("max_jobs")
    max_jobs = None
    if max_jobs_raw:
        try:
            max_jobs = int(max_jobs_raw)
        except (ValueError, TypeError):
            ws.send("ERROR: Invalid parameter 'max_jobs' — must be an integer.\n")
            return
    search_queries = params.get("search_queries") or []
    locations      = params.get("locations") or []
    sources        = params.get("sources") or []

    collector_args = ["--days", str(days)]
    if max_jobs:
        collector_args += ["--max-jobs", str(max_jobs)]
    if search_queries:
        collector_args += ["--search-queries"] + search_queries
    if locations:
        collector_args += ["--locations"] + locations
    if sources:
        collector_args += ["--sources"] + sources

    with _open_log() as lf:
        header = f"=== COLLECTOR (days={days}, max_jobs={max_jobs or 'unlimited'}) ===\n"
        lf.write(header)
        ws.send(header)
        rc = _run_script(ws, os.path.join(ROOT, "collector", "runner.py"), collector_args, _log_file=lf)

        if rc != 0:
            msg = f"\nCollector failed (exit code {rc}). Skipping evaluator.\n"
            lf.write(msg)
            ws.send(msg)
        else:
            msg = "\n=== EVALUATOR ===\n"
            lf.write(msg)
            ws.send(msg)
            _run_script(ws, os.path.join(ROOT, "evaluator", "runner.py"), _log_file=lf)

    _agent_process = None
    try:
        ws.send("\n__DONE__\n")
    except Exception:
        pass


@sock.route("/ws/backfill")
def backfill_ws(ws):
    global _agent_process

    if _is_run_active():
        ws.send("ERROR: Agent is already running.\n")
        return

    script = os.path.join(ROOT, "scripts", "backfill_descriptions.py")

    with _open_log() as lf:
        header = "=== BACKFILL DESCRIPTIONS ===\n"
        lf.write(header)
        ws.send(header)
        rc = _run_script(ws, script, _log_file=lf)

        if rc == 0:
            msg = "\n=== EVALUATOR ===\n"
            lf.write(msg)
            ws.send(msg)
            _run_script(ws, os.path.join(ROOT, "evaluator", "runner.py"), _log_file=lf)

    _agent_process = None
    try:
        ws.send("\n__DONE__\n")
    except Exception:
        pass
