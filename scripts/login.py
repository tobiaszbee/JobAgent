"""Authenticate this JobAgent installation against JobAgentWeb, once. Every
script and the local dashboard reuse the saved session afterward — see
api_client.py.

The dashboard's own /login page (web/app.py) covers this interactively now;
use this script instead for headless/server installs with no browser access
to the dashboard's port. Run:

    python scripts/login.py
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_client
from config import JOBAGENTWEB_BASE_URL


def main():
    print(f"Logging in to {JOBAGENTWEB_BASE_URL}")
    print(f"(No account yet? Register at {JOBAGENTWEB_BASE_URL}/register first.)")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")

    try:
        api_client.login(username, password)
    except api_client.NotLoggedInError as e:
        raise SystemExit(f"Login failed: {e}")

    print("Logged in — session saved. You won't need to do this again until it expires.")


if __name__ == "__main__":
    main()
