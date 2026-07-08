from flask import Flask, render_template
from db.migrations import init_db
from db.repositories import session_repository
from web.routes import jobs, criteria, runner, cv, sources, preferences, ranking, query_expansion, evaluation

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["TEMPLATES_AUTO_RELOAD"] = True

app.register_blueprint(jobs.bp)
app.register_blueprint(criteria.bp)
app.register_blueprint(runner.bp)
app.register_blueprint(cv.bp)
app.register_blueprint(sources.bp)
app.register_blueprint(preferences.bp)
app.register_blueprint(ranking.bp)
app.register_blueprint(query_expansion.bp)
app.register_blueprint(evaluation.bp)
runner.init_sock(app)


@app.get("/")
def dashboard():
    return render_template("dashboard.html")


if __name__ == "__main__":
    init_db()
    session_repository.cancel_active()  # clear any stale running sessions from a previous crash
    print("Starting Job Agent Dashboard...")
    print("Open: http://localhost:5000")
    app.run(debug=False, port=5000)
