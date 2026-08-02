import logging

from flask import Flask, jsonify, redirect, render_template, request

import api_client
from config import JOBAGENTWEB_BASE_URL
from db.repositories import candidate_preferences_repository, cv_repository, session_repository
from web.routes import (
    candidate_preferences, jobs, jobs_admin, criteria, runner, cv, sources, preferences,
    query_expansion, evaluation, search_queries,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["TEMPLATES_AUTO_RELOAD"] = True

app.register_blueprint(jobs.bp)
app.register_blueprint(evaluation.bp)
app.register_blueprint(jobs_admin.bp)
app.register_blueprint(criteria.bp)
app.register_blueprint(runner.bp)
app.register_blueprint(cv.bp)
app.register_blueprint(sources.bp)
app.register_blueprint(preferences.bp)
app.register_blueprint(candidate_preferences.bp)
app.register_blueprint(query_expansion.bp)
app.register_blueprint(search_queries.bp)
runner.init_sock(app)


@app.before_request
def require_login():
    if request.path == "/login" or request.path.startswith("/static/"):
        return
    if not api_client.logged_in():
        return redirect("/login")


@app.errorhandler(api_client.NotLoggedInError)
def handle_session_expired(e):
    """Session existed but JobAgentWeb rejected it (expired/invalid) — send the
    user back to /login instead of a raw 500, distinguishing JSON callers (the
    dashboard's own fetch()) from full-page navigations."""
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e)}), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            api_client.login(username, password)
        except api_client.NotLoggedInError as e:
            error = str(e)
        else:
            return redirect("/")
    return render_template("login.html", error=error, jobagentweb_base_url=JOBAGENTWEB_BASE_URL)


@app.get("/")
def dashboard():
    if not candidate_preferences_repository.get_active():
        return render_template("landing.html")
    return render_template("dashboard.html")


@app.get("/questionnaire")
def questionnaire():
    if not cv_repository.get_active():
        return redirect("/")
    return render_template("questionnaire.html")


@app.get("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


def _clear_stale_session_at_startup():
    """Clear any stale 'running' session left over from a previous crash —
    best-effort, not fatal: logged_in() only checks that a session file
    exists, not that it's still valid, so a stale/expired cookie (401) or a
    momentary JobAgentWeb/tunnel hiccup here must not take down the whole app
    before it can even serve /login."""
    if not api_client.logged_in():
        return
    try:
        session_repository.cancel_active()
    except Exception:
        logging.getLogger(__name__).warning("Could not clear stale session at startup", exc_info=True)


if __name__ == "__main__":
    _clear_stale_session_at_startup()
    print("Starting Job Agent Dashboard...")
    print("Open: http://localhost:5000")
    app.run(debug=False, port=5000)
