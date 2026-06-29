import os
import sys
import json
import webbrowser
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import AGENT
from src.db.repositories import job_repository as jobs


def generate():
    os.makedirs(AGENT["reports_path"], exist_ok=True)

    all_jobs = jobs.get_for_report()
    stats = jobs.get_stats()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    filename = datetime.now().strftime("%Y%m%d_%H%M") + "_report.html"
    path = os.path.join(AGENT["reports_path"], filename)

    env = Environment(
        loader=FileSystemLoader(os.path.join(ROOT, "src", "templates"))
    )
    template = env.get_template("report.html")

    html = template.render(
        jobs=all_jobs,
        jobs_json=json.dumps(all_jobs, ensure_ascii=False, default=str),
        stats=stats,
        timestamp=timestamp,
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report saved: {path}")
    webbrowser.open(f"file://{os.path.abspath(path)}")
    return path


if __name__ == "__main__":
    generate()
