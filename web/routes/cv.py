import io
import json

import PyPDF2
import anthropic
from flask import Blueprint, jsonify, request

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from db.repositories import cv_repository

bp = Blueprint("cv", __name__)

_PARSE_PROMPT = """Extract structured information from this CV/resume.
Respond ONLY with JSON, no other text:
{
    "stack": ["list of technologies, languages, frameworks"],
    "years_experience": <integer or null>,
    "seniority": "Junior|Mid|Senior|Lead|Principal",
    "location": "city, country",
    "remote_preference": "fully remote|hybrid|on-site|flexible",
    "raw_summary": "2-3 sentence summary of the candidate"
}"""


def _extract_text(file_bytes: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_with_claude(raw_text: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": f"{_PARSE_PROMPT}\n\nCV text:\n{raw_text[:4000]}"}],
    )
    raw = response.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


@bp.get("/api/cv")
def list_profiles():
    return jsonify(cv_repository.list_all())


@bp.post("/api/cv/upload")
def upload_cv():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400
    try:
        raw_text = _extract_text(file.read())
    except Exception as e:
        return jsonify({"error": f"Failed to read PDF: {e}"}), 400
    if not raw_text.strip():
        return jsonify({"error": "Could not extract text from PDF (may be a scanned image — use a text-based PDF)"}), 400
    try:
        parsed = _parse_with_claude(raw_text)
    except Exception as e:
        return jsonify({"error": f"Failed to parse CV with Claude: {e}"}), 500
    id_ = cv_repository.insert(file.filename, raw_text, parsed)
    return jsonify({"ok": True, "id": id_, "parsed": parsed})


@bp.post("/api/cv/<int:id>/activate")
def activate_profile(id):
    cv_repository.set_active(id)
    return jsonify({"ok": True})
