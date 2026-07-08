from db.repositories import cv_repository


def load_active_profile() -> str:
    """Return the active CV profile as a formatted prompt string.
    Raises ValueError if no profile has been uploaded yet."""
    profile = cv_repository.get_active()
    if not profile:
        raise ValueError(
            "No active CV profile found. Upload your CV via the dashboard → CV tab."
        )
    parsed = profile["parsed"]
    stack = ", ".join(parsed.get("stack") or []) or "(not specified)"
    lines = [
        "CANDIDATE:",
        f"- {parsed.get('seniority', 'Engineer')}, {parsed.get('years_experience', '?')}+ years experience",
        f"- Stack: {stack}",
        f"- Location: {parsed.get('location', 'not specified')}",
        f"- Remote preference: {parsed.get('remote_preference', 'fully remote')}",
    ]
    summary = (parsed.get("raw_summary") or "").strip()
    if summary:
        lines.append(f"- {summary}")
    return "\n".join(lines)
