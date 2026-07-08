import glob
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from flask import Blueprint
from flask_sock import Sock

bp = Blueprint("runner", __name__)
sock = Sock()

ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGS_DIR = os.path.join(ROOT, "data", "logs")

# Prefer the project venv so subprocesses have all dependencies (voyageai etc.)
_venv_python = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
PYTHON = _venv_python if os.path.exists(_venv_python) else sys.executable
_KEEP_LOGS = 30

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


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill process and all its children (handles orphaned Playwright/Chrome on Windows)."""
    try:
        if sys.platform == "win32":
            subprocess.call(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            import signal, os
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        proc.terminate()


@bp.post("/api/agent/stop")
def agent_stop():
    global _agent_process
    from db.repositories import session_repository
    killed = False
    if _agent_process is not None and _agent_process.poll() is None:
        _kill_process_tree(_agent_process)
        _agent_process = None
        killed = True
    session_repository.cancel_active()
    return {"ok": True, "killed": killed}


@bp.get("/api/agent/logs")
def agent_logs():
    path = _latest_log()
    if not path:
        return {"lines": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return {"lines": [l.rstrip("\n") for l in lines[-200:]]}
    except FileNotFoundError:
        return {"lines": []}


@bp.get("/api/agent/log-files")
def agent_log_files():
    files = sorted(glob.glob(os.path.join(LOGS_DIR, "run_*.log")), reverse=True)
    return {"files": [os.path.basename(f) for f in files[:50]]}


def _safe_send(ws, msg: str) -> None:
    try:
        ws.send(msg)
    except Exception:
        pass


def _run_script(ws, script_path: str, args: list[str] = [], log_file=None) -> int:
    global _agent_process
    cmd = [PYTHON, "-u", script_path] + args
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT
    env["PYTHONIOENCODING"] = "utf-8"
    _agent_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
        cwd=ROOT,
        env=env,
    )
    ws_alive = True
    for line in _agent_process.stdout:
        if log_file:
            log_file.write(line)
            log_file.flush()
        if ws_alive:
            try:
                ws.send(line)
            except Exception:
                ws_alive = False  # keep draining stdout so process doesn't block
    _agent_process.wait()
    return _agent_process.returncode


def _open_log():
    os.makedirs(LOGS_DIR, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOGS_DIR, f"run_{ts}.log")
    _rotate_logs()
    return open(path, "w", encoding="utf-8")


def _rotate_logs():
    files = sorted(glob.glob(os.path.join(LOGS_DIR, "run_*.log")))
    for old in files[:-_KEEP_LOGS]:
        try:
            os.remove(old)
        except OSError:
            pass


def _latest_log() -> str | None:
    files = sorted(glob.glob(os.path.join(LOGS_DIR, "run_*.log")))
    return files[-1] if files else None


@sock.route("/ws/agent")
def agent_ws(ws):
    global _agent_process

    with _lock:
        if _is_run_active():
            ws.send("ERROR: Agent is already running.\n")
            return

    raw_params = ws.receive()
    try:
        params = json.loads(raw_params)
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

    with _open_log() as log_file:
        header = f"=== COLLECTOR (days={days}, max_jobs={max_jobs or 'unlimited'}) ===\n"
        log_file.write(header)
        _safe_send(ws, header)
        exit_code = _run_script(ws, os.path.join(ROOT, "collector", "runner.py"), collector_args, log_file=log_file)

        if exit_code != 0:
            msg = f"\nCollector failed (exit code {exit_code}). Skipping evaluator.\n"
            log_file.write(msg)
            _safe_send(ws, msg)
        else:
            msg = "\n=== DISTILL PREFERENCES ===\n"
            log_file.write(msg)
            _safe_send(ws, msg)
            _run_script(ws, os.path.join(ROOT, "scripts", "distill_preferences.py"), log_file=log_file)

            msg = "\n=== EVALUATOR ===\n"
            log_file.write(msg)
            _safe_send(ws, msg)
            _run_script(ws, os.path.join(ROOT, "evaluator", "runner.py"), log_file=log_file)

            msg = "\n=== AI RANKING ===\n"
            log_file.write(msg)
            _safe_send(ws, msg)
            _run_script(ws, os.path.join(ROOT, "scripts", "rank_jobs.py"), log_file=log_file)

    _agent_process = None
    _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/backfill")
def backfill_ws(ws):
    global _agent_process

    with _lock:
        if _is_run_active():
            ws.send("ERROR: Agent is already running.\n")
            return

    script = os.path.join(ROOT, "scripts", "backfill_descriptions.py")

    with _open_log() as log_file:
        header = "=== BACKFILL DESCRIPTIONS ===\n"
        log_file.write(header)
        _safe_send(ws, header)
        exit_code = _run_script(ws, script, log_file=log_file)

        if exit_code == 0:
            msg = "\n=== EVALUATOR ===\n"
            log_file.write(msg)
            _safe_send(ws, msg)
            _run_script(ws, os.path.join(ROOT, "evaluator", "runner.py"), log_file=log_file)

    _agent_process = None
    _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/reevaluate-rejected")
def reevaluate_rejected_ws(ws):
    global _agent_process

    with _lock:
        if _is_run_active():
            ws.send("ERROR: Agent is already running.\n")
            return

    script = os.path.join(ROOT, "scripts", "reevaluate_rejected.py")

    with _open_log() as log_file:
        header = "=== RE-EVALUATE AUTO-REJECTED ===\n"
        log_file.write(header)
        _safe_send(ws, header)
        _run_script(ws, script, log_file=log_file)

    _agent_process = None
    _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/rescore-new")
def rescore_new_ws(ws):
    global _agent_process

    with _lock:
        if _is_run_active():
            ws.send("ERROR: Agent is already running.\n")
            return

    with _open_log() as log_file:
        header = "=== RE-SCORE NEW JOBS ===\n"
        log_file.write(header)
        _safe_send(ws, header)

        msg = "--- Distilling preferences...\n"
        log_file.write(msg)
        _safe_send(ws, msg)
        _run_script(ws, os.path.join(ROOT, "scripts", "distill_preferences.py"), log_file=log_file)

        msg = "--- Scoring...\n"
        log_file.write(msg)
        _safe_send(ws, msg)
        _run_script(ws, os.path.join(ROOT, "scripts", "rescore_new.py"), log_file=log_file)

    _agent_process = None
    _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/rank")
def rank_ws(ws):
    global _agent_process

    with _lock:
        if _is_run_active():
            ws.send("ERROR: Agent is already running.\n")
            return

    with _open_log() as log_file:
        header = "=== AI RANKING (Voyage + Claude Opus) ===\n"
        log_file.write(header)
        _safe_send(ws, header)
        _run_script(ws, os.path.join(ROOT, "scripts", "rank_jobs.py"), log_file=log_file)

    _agent_process = None
    _safe_send(ws, "\n__DONE__\n")
