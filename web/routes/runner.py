import glob
import json
import math
import os
import subprocess
import sys
import threading
from datetime import datetime
from flask import Blueprint
from flask_sock import Sock

from db.repositories import session_repository, usage_repository

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
_run_active = False


def init_sock(app):
    sock.init_app(app)


_DEFAULT_DAYS_NO_PRIOR_RUN = 7


def _days_since_last_run() -> int:
    """Collector sources filter by whole days, not exact timestamps — so "since last
    run" is approximated as the number of days back that comfortably covers the time
    since the last successful run, rounded up. Slight overlap is harmless (the
    collector already dedupes by URL); under-covering would silently miss postings."""
    last_finished = session_repository.get_last_finished_at()
    if not last_finished:
        return _DEFAULT_DAYS_NO_PRIOR_RUN
    try:
        last_dt = datetime.strptime(last_finished, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return _DEFAULT_DAYS_NO_PRIOR_RUN
    hours_elapsed = (datetime.utcnow() - last_dt).total_seconds() / 3600
    return max(1, math.ceil(hours_elapsed / 24))


def _is_run_active() -> bool:
    if _run_active:
        return True
    if _agent_process is not None and _agent_process.poll() is None:
        return True
    from db.repositories import session_repository
    return session_repository.has_active_run()


class _RunGuard:
    """Marks a websocket-triggered run (agent/backfill/rescore/reevaluate/rank — they
    all share the same _agent_process global) as active for the guard's *entire*
    lifetime, not just until the first subprocess spawns. The old pattern only held
    _lock around the initial _is_run_active() check, then released it before
    ws.receive() (which can block indefinitely on a slow client) and before
    _run_script() actually set _agent_process — so two near-simultaneous websocket
    connections could both pass the check before either process existed. A multi-stage
    run (agent_ws's collector → extractor → evaluator → ... sequence) had the same gap
    between stages, however briefly, since _agent_process briefly points at an
    already-exited Popen between _run_script() calls. Usage: `with _RunGuard() as
    acquired: if not acquired: ...bail out...`."""

    def __enter__(self) -> bool:
        global _run_active
        with _lock:
            if _is_run_active():
                return False
            _run_active = True
            return True

    def __exit__(self, *_exc):
        global _run_active
        _run_active = False


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


# Stages run after a successful collection, in order: (header, script path, args).
# Pulled out as a plain function (rather than inlined in agent_ws) so the sequence —
# in particular that EXTRACTOR sits BEFORE EVALUATOR — is unit-testable without a
# websocket. EXTRACTOR must run first: evaluator/dealbreakers.py's pre-LLM filter
# reads structured_data, and jobs never re-enter the "unscored" pool once the
# evaluator scores them — so if extraction ran after evaluation, freshly-collected
# jobs would always hit the dealbreaker filter with no structured_data yet, and
# never get a second chance. Running extraction first means listwise ranking also
# always sees fresh structured_data tags, as a side benefit.
def _post_collect_stages() -> list[tuple[str, str, list[str]]]:
    return [
        ("DISTILL PREFERENCES", os.path.join(ROOT, "scripts", "distill_preferences.py"), []),
        ("EXTRACTOR",           os.path.join(ROOT, "scripts", "extract_jobs.py"), []),
        ("EVALUATOR",           os.path.join(ROOT, "evaluator", "runner.py"), []),
        ("PRUNE QUERIES",       os.path.join(ROOT, "scripts", "prune_search_queries.py"), []),
        ("AI RANKING",          os.path.join(ROOT, "scripts", "rank_jobs.py"), []),
    ]


@sock.route("/ws/agent")
def agent_ws(ws):
    global _agent_process

    with _RunGuard() as acquired:
        if not acquired:
            ws.send("ERROR: Agent is already running.\n")
            return

        raw_params = ws.receive()
        try:
            params = json.loads(raw_params)
        except Exception:
            params = {}

        if params.get("since_last_run"):
            days = _days_since_last_run()
        else:
            try:
                days = int(params.get("days", 1))
            except (ValueError, TypeError):
                ws.send("ERROR: Invalid parameter 'days' — must be an integer.\n")
                return

        collector_args = ["--days", str(days)]
        started_at = usage_repository.now_iso()

        with _open_log() as log_file:
            header = f"=== COLLECTOR (days={days}) ===\n"
            log_file.write(header)
            _safe_send(ws, header)
            exit_code = _run_script(ws, os.path.join(ROOT, "collector", "runner.py"), collector_args, log_file=log_file)

            if exit_code != 0:
                msg = f"\nCollector failed (exit code {exit_code}). Skipping evaluator.\n"
                log_file.write(msg)
                _safe_send(ws, msg)
            else:
                for label, script_path, args in _post_collect_stages():
                    msg = f"\n=== {label} ===\n"
                    log_file.write(msg)
                    _safe_send(ws, msg)
                    _run_script(ws, script_path, args, log_file=log_file)

        usage_repository.record_run_summary("run_agent", started_at)
        _agent_process = None
        _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/backfill")
def backfill_ws(ws):
    global _agent_process

    with _RunGuard() as acquired:
        if not acquired:
            ws.send("ERROR: Agent is already running.\n")
            return

        script = os.path.join(ROOT, "scripts", "backfill_descriptions.py")
        started_at = usage_repository.now_iso()

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

        usage_repository.record_run_summary("backfill", started_at)
        _agent_process = None
        _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/reevaluate-rejected")
def reevaluate_rejected_ws(ws):
    global _agent_process

    with _RunGuard() as acquired:
        if not acquired:
            ws.send("ERROR: Agent is already running.\n")
            return

        script = os.path.join(ROOT, "scripts", "reevaluate_rejected.py")
        started_at = usage_repository.now_iso()

        with _open_log() as log_file:
            header = "=== RE-EVALUATE AUTO-REJECTED ===\n"
            log_file.write(header)
            _safe_send(ws, header)
            _run_script(ws, script, log_file=log_file)

        usage_repository.record_run_summary("reevaluate_rejected", started_at)
        _agent_process = None
        _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/rescore-new")
def rescore_new_ws(ws):
    global _agent_process

    with _RunGuard() as acquired:
        if not acquired:
            ws.send("ERROR: Agent is already running.\n")
            return

        started_at = usage_repository.now_iso()

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

        usage_repository.record_run_summary("rescore_new", started_at)
        _agent_process = None
        _safe_send(ws, "\n__DONE__\n")


@sock.route("/ws/rank")
def rank_ws(ws):
    global _agent_process

    with _RunGuard() as acquired:
        if not acquired:
            ws.send("ERROR: Agent is already running.\n")
            return

        started_at = usage_repository.now_iso()

        with _open_log() as log_file:
            header = "=== AI RANKING (Voyage + Claude Opus) ===\n"
            log_file.write(header)
            _safe_send(ws, header)
            _run_script(ws, os.path.join(ROOT, "scripts", "rank_jobs.py"), log_file=log_file)

        usage_repository.record_run_summary("rank", started_at)
        _agent_process = None
        _safe_send(ws, "\n__DONE__\n")
