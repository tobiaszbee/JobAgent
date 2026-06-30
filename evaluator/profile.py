from db.repositories import cv_repository


def load_active_profile() -> str:
    """Return the active CV profile as a formatted prompt string.
    Raises ValueError if no profile has been uploaded yet."""
    profile = cv_repository.get_active()
    if not profile:
        raise ValueError(
            "No active CV profile found. Upload your CV via the dashboard → CV tab."
        )
    p = profile["parsed"]
    stack = ", ".join(p.get("stack") or []) or "(not specified)"
    lines = [
        "CANDIDATE:",
        f"- {p.get('seniority', 'Engineer')}, {p.get('years_experience', '?')}+ years experience",
        f"- Stack: {stack}",
        f"- Location: {p.get('location', 'not specified')}",
        f"- Remote preference: {p.get('remote_preference', 'fully remote')}",
    ]
    summary = (p.get("raw_summary") or "").strip()
    if summary:
        lines.append(f"- {summary}")
    return "\n".join(lines)
