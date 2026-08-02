from db.repositories import candidate_preferences_repository, cv_repository

# Fields worth folding into a semantic retrieval query — the ones with real
# positive lexical/semantic overlap against job description text. Deliberately
# excludes excluded_company_types/excluded_industries/avoided_tech: embeddings
# and cross-encoder rerank have no way to represent negation from a bare word
# in a query — including e.g. "agency" from an excluded_company_types entry
# would just pull MORE agency jobs toward the top, the opposite of intent.
# open_notes is included as full free text (not list terms) since a real
# sentence like "not interested in gambling companies" gives the embedding
# model actual negation context that a bare listed word can't.
_RETRIEVAL_LIST_FIELDS = ["role_types", "preferred_company_types", "preferred_industries", "extra_tech"]

# Maps a candidate_preferences list field to its rendered label — order here is
# the order they appear in the prompt.
_LIST_FIELD_LABELS = [
    ("role_types", "Desired role type(s)"),
    ("preferred_company_types", "Prefers company type(s)"),
    ("excluded_company_types", "Wants to avoid company type(s)"),
    ("preferred_industries", "Prefers industry/industries"),
    ("excluded_industries", "Wants to avoid industry/industries"),
    ("extra_tech", "Also interested in"),
    ("avoided_tech", "Wants to avoid working with"),
]


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


def load_questionnaire_preferences() -> str:
    """Return the candidate's raw questionnaire answers (candidate_preferences_repository)
    as a formatted prompt block, or "" if none saved yet. Distinct from both
    load_active_profile() (parsed CV facts) and the learned preference profile
    (preference_agent — signals inferred from applied/rejected history): this is
    the candidate's own direct, current, stated answers, collected but previously
    never reaching any LLM prompt. Deliberately restates fields already enforced
    as hard dealbreakers (evaluator/dealbreakers.py) too — that filter skips on
    missing/unclear structured data by design, so a job it let through can still
    carry the relevant info in free-text description that only the LLM will catch."""
    prefs = candidate_preferences_repository.get_active()
    if not prefs:
        return ""

    lines = []

    work_mode = prefs.get("work_mode") or []
    if work_mode:
        lines.append(f"- Work mode: {', '.join(work_mode)}")
    if prefs.get("remote_countries"):
        lines.append(f"- Remote must be available in: {', '.join(prefs['remote_countries'])}")
    if prefs.get("hybrid_cities"):
        lines.append(f"- OK with hybrid in: {', '.join(prefs['hybrid_cities'])}")
    if prefs.get("seniority_levels"):
        lines.append(f"- Seniority level(s) wanted: {', '.join(prefs['seniority_levels'])}")

    for field, label in _LIST_FIELD_LABELS:
        if prefs.get(field):
            lines.append(f"- {label}: {', '.join(prefs[field])}")

    salary_min = prefs.get("salary_min")
    if salary_min:
        currency = prefs.get("salary_currency") or ""
        lines.append(f"- Minimum salary: {salary_min} {currency}".rstrip())

    languages = prefs.get("languages") or []
    lang_str = ", ".join(
        f"{lang.get('language')} ({lang.get('level')})" for lang in languages if lang.get("language")
    )
    if lang_str:
        lines.append(f"- Languages: {lang_str}")

    open_notes = (prefs.get("open_notes") or "").strip()
    if open_notes:
        lines.append(f'- In their own words: "{open_notes}"')

    if not lines:
        return ""
    return "CANDIDATE QUESTIONNAIRE (their own stated preferences):\n" + "\n".join(lines)


def build_retrieval_query(candidate_profile: str) -> str:
    """Combine the CV profile with a compact questionnaire summary for use as the
    query text for both semantic retrieval (embeddings/indexer.py::build_ideal_vector's
    cold-start fallback) and cross-encoder reranking (ranker/reranker.py::rerank_jobs)
    — both previously only ever saw the CV, missing everything the candidate told the
    questionnaire directly (extra tech interests, preferred industries, etc.). Kept
    dense and unlabeled, unlike load_questionnaire_preferences() above (meant for an
    LLM prompt): rerank_jobs truncates its query to 500 chars, so every character here
    should be a real retrieval term, not prose structure."""
    prefs = candidate_preferences_repository.get_active()
    if not prefs:
        return candidate_profile

    terms = []
    for field in _RETRIEVAL_LIST_FIELDS:
        terms.extend(prefs.get(field) or [])
    open_notes = (prefs.get("open_notes") or "").strip()
    if open_notes:
        terms.append(open_notes)

    if not terms:
        return candidate_profile

    suffix = "Preferences: " + ", ".join(terms)
    return f"{candidate_profile}\n{suffix}" if candidate_profile else suffix
