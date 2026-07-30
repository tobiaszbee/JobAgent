"""Thin HTTP client for JobAgentWeb — the sole data store now. Every db/repositories/*.py
function goes through here instead of raw SQL. Auth is a single persisted session
cookie (see login()), shared by every script and the local Flask dashboard alike:
this JobAgent installation acts as one already-authenticated identity, not a
per-caller login.
"""
import json
import time
from pathlib import Path

import httpx

from config import JOBAGENTWEB_BASE_URL

_SESSION_FILE = Path.home() / ".jobagent" / "session.json"


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


def register(username: str, password: str) -> None:
    """Registers a new account on JobAgentWeb and persists its session cookie,
    same as login(). Mirrors JobAgentWeb's POST /register form contract."""
    resp = httpx.post(
        f"{JOBAGENTWEB_BASE_URL}/register",
        data={"username": username, "password": password, "password_confirm": password},
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

    last_error = None
    for attempt in range(3):
        try:
            with httpx.Client(base_url=JOBAGENTWEB_BASE_URL, cookies={"session": cookie}, timeout=30.0) as client:
                resp = client.request(method, path, **kwargs)
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
