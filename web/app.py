from flask import Flask, redirect, render_template
from db.repositories import candidate_preferences_repository, cv_repository, session_repository
from web.routes import (
    candidate_preferences, jobs, jobs_admin, criteria, runner, cv, sources, preferences,
    ranking, query_expansion, evaluation, search_queries,
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
app.register_blueprint(ranking.bp)
app.register_blueprint(query_expansion.bp)
app.register_blueprint(search_queries.bp)
runner.init_sock(app)


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


if __name__ == "__main__":
    session_repository.cancel_active()  # clear any stale running sessions from a previous crash
    print("Starting Job Agent Dashboard...")
    print("Open: http://localhost:5000")
    app.run(debug=False, port=5000)
