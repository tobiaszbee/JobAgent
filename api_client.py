"""Thin HTTP client for JobAgentWeb — the sole data store now. Every db/repositories/*.py
function goes through here instead of raw SQL. Auth is a single persisted session
cookie (see login()), shared by every script and the local Flask dashboard alike:
this JobAgent installation acts as one already-authenticated identity, not a
per-caller login.
"""
import json
import os
import time
from pathlib import Path

import httpx

from config import JOBAGENTWEB_BASE_URL

_SESSION_FILE = Path.home() / ".jobagent" / "session.json"

# Reused across every call instead of opening a fresh TCP/TLS connection per
# request — every db/repositories/*.py function goes through request() below,
# so a full pipeline run used to pay a new handshake hundreds of times over,
# on top of the WireGuard tunnel's own latency. Never explicitly closed: this
# module is used both by short-lived scripts (the process exit cleans up the
# socket) and the long-running dashboard (where staying open all run is the
# point).
_client = httpx.Client(base_url=JOBAGENTWEB_BASE_URL, timeout=30.0)


class NotLoggedInError(Exception):
    pass


class ApiError(Exception):
    """A request reached the server but it returned an error response."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def _load_cookie() -> str | None:
    if not _SESSION_FILE.exists():
        return None
    try:
        return json.loads(_SESSION_FILE.read_text()).get("session_cookie")
    except (json.JSONDecodeError, OSError):
        return None


def _save_cookie(cookie_value: str) -> None:
    _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_FILE.write_text(json.dumps({"session_cookie": cookie_value}))
    # Owner-only — this file is a live, unattended login for this JobAgentWeb
    # account; on a shared machine, default permissions would hand it to anyone
    # else on the box. No-op on Windows (POSIX mode bits don't map to NTFS ACLs),
    # but real protection on macOS/Linux, which this same code path also runs on.
    os.chmod(_SESSION_FILE, 0o600)


def login(username: str, password: str) -> None:
    """Authenticates against JobAgentWeb and persists the session cookie to
    ~/.jobagent/session.json for every future call from this machine."""
    resp = httpx.post(
        f"{JOBAGENTWEB_BASE_URL}/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    cookie = resp.cookies.get("session")
    if resp.status_code != 303 or not cookie:
        raise NotLoggedInError("Login failed — check your username and password.")
    _save_cookie(cookie)


def register(username: str, password: str, invite_code: str = "") -> None:
    """Registers a new account on JobAgentWeb and persists its session cookie,
    same as login(). Mirrors JobAgentWeb's POST /register form contract, which
    requires a valid invite_code whenever JobAgentWeb has one configured."""
    resp = httpx.post(
        f"{JOBAGENTWEB_BASE_URL}/register",
        data={"username": username, "password": password, "password_confirm": password, "invite_code": invite_code},
        follow_redirects=False,
    )
    cookie = resp.cookies.get("session")
    if resp.status_code != 303 or not cookie:
        raise NotLoggedInError(f"Registration failed: {resp.text}")
    _save_cookie(cookie)


def logged_in() -> bool:
    return _load_cookie() is not None


def request(method: str, path: str, **kwargs):
    """Authenticated request against JobAgentWeb. Retries transient network/tunnel
    blips with backoff (matching the old direct-Postgres adapter's behavior) —
    never retries a 4xx, since that's a real error, not a connectivity hiccup."""
    cookie = _load_cookie()
    if not cookie:
        raise NotLoggedInError(
            "Not logged in. Run `python scripts/login.py`, or register an account "
            f"at {JOBAGENTWEB_BASE_URL}/register first."
        )

    # Cleared and re-set on every call, not just set once: httpx.Client auto-
    # captures Set-Cookie from every response into its own jar by default, and
    # Starlette's SessionMiddleware re-signs and re-sends the session cookie on
    # every response — the auto-captured entry and this explicit .set() can
    # coexist as separate (domain, path) entries in the jar instead of one
    # replacing the other, so a request can end up sending two "session"
    # cookies at once, with the server's cookie parser picking whichever it
    # sees first (observed in practice: a stale cookie from a previous login
    # sharing this same process, e.g. two isolated test users in one session).
    _client.cookies.clear()
    _client.cookies.set("session", cookie)

    last_error = None
    for attempt in range(3):
        try:
            resp = _client.request(method, path, **kwargs)
            break
        except httpx.TransportError as e:
            last_error = e
            time.sleep(0.5 * (attempt + 1))
    else:
        raise last_error

    if resp.status_code == 401:
        raise NotLoggedInError("Session expired or invalid — run `python scripts/login.py` again.")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except json.JSONDecodeError:
            detail = resp.text
        raise ApiError(resp.status_code, detail)
    return resp


def get(path: str, **kwargs) -> httpx.Response:
    return request("GET", path, **kwargs)


def post(path: str, **kwargs) -> httpx.Response:
    return request("POST", path, **kwargs)


def patch(path: str, **kwargs) -> httpx.Response:
    return request("PATCH", path, **kwargs)


def delete(path: str, **kwargs) -> httpx.Response:
    return request("DELETE", path, **kwargs)
