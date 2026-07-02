import json
import time
import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _build_examples_section(positive: list[dict], negative: list[dict]) -> str:
    lines = []
    if positive:
        lines.append("EXAMPLES OF JOBS I APPLIED TO (high quality — learn what I like):")
        for ex in positive:
            desc = ex["description"][:200].replace("\n", " ") if ex.get("description") else ""
            lines.append(f'- "{ex["title"]}" @ {ex["company"]}: {desc}...')
        lines.append("")
    if negative:
        lines.append("EXAMPLES OF JOBS I REJECTED (learn what to avoid):")
        for ex in negative:
            desc = ex["description"][:150].replace("\n", " ") if ex.get("description") else ""
            reason = (ex.get("rejection_reason") or ex.get("score_reason") or "")[:150]
            reason_str = f" [My reason: {reason}]" if reason else ""
            lines.append(f'- "{ex["title"]}" @ {ex["company"]}: {desc}...{reason_str}')
        lines.append("")
    return "\n".join(lines) + "\n" if lines else ""


def _build_preferences_section(learned_preferences: str) -> str:
    if not learned_preferences.strip():
        return ""
    return (
        "LEARNED PREFERENCE PROFILE"
        " (distilled from all feedback — use as high-priority scoring context):\n"
        f"{learned_preferences.strip()}\n\n"
    )


def build_system_prompt(
    criteria: dict,
    positive_examples: list[dict],
    negative_examples: list[dict],
    candidate_profile: str = "",
    learned_preferences: str = "",
) -> str:
    """Build the system prompt. Call once per batch and reuse across jobs."""
    prefs_section = _build_preferences_section(learned_preferences)
    examples_section = _build_examples_section(positive_examples, negative_examples)

    required = criteria.get("required", [])
    required_extra = ("\n" + "\n".join(f"- {r}" for r in required)) if required else ""

    rejected = criteria.get("rejected", [])
    rejected_extra = (
        "\n\nADDITIONAL USER-DEFINED REJECTION RULES (reject if any apply):\n"
        + "\n".join(f"- {r}" for r in rejected)
    ) if rejected else ""

    preferred = criteria.get("preferred", [])
    preferred_section = "\n".join(f"- {p}" for p in preferred) if preferred else "- (none configured)"

    return f"""You are evaluating job listings for a candidate.

{candidate_profile}

{prefs_section}{examples_section}REQUIRED (must have all):
- PHP mentioned in the job description — NOTE: Laravel, Symfony, WordPress are PHP frameworks, so they count as PHP
- Remote work possible{required_extra}

PREFERRED (increases score):
{preferred_section}

AUTOMATIC REJECTION — only reject if the description contains one of these EXACT situations:
1. Candidate must physically relocate or be resident in a specific country
2. Role is on-site with NO remote option
3. Role is junior or intern level
4. Job listing is not in English
5. "Remote, UK based" or "UK based, remote" — means candidate must be in UK
6. "Remote within UK" or "UK remote only" — means candidate must be in UK
7. "Must be eligible to work in the UK" — means physical presence in UK required{rejected_extra}

DO NOT reject for:
- Company location ("Berlin-based company", "Paris-based startup", "London HQ")
- "Germany (Remote)", "UK (Remote)", "France (Remote)" in location field — these mean remote IS available
- Visa sponsorship mentions — candidate works remotely from Poland, needs no visa anywhere
- Work authorization mentions — same reason
- "United States (Remote)", "Canada (Remote)" — remote from Poland is fine
- "EMEA" region — Poland is in EMEA
- "Europe" region — Poland is in Europe

Respond ONLY with JSON, no other text:
{{
    "score": <0-10>,
    "score_reason": "<one sentence>",
    "matched_required": [],
    "matched_preferred": [],
    "dealbreakers_found": []
}}"""


def _build_user_message(job: dict) -> str:
    return (
        f"Evaluate this job:\n\n"
        f"Title: {job['title']}\n"
        f"Company: {job['company']}\n"
        f"Location: {job['location']}\n"
        f"Description: {(job.get('description') or '')[:3000]}"
    )


_ERROR_RESULT = {
    "score": 0.0,
    "score_reason": "",
    "matched_required": [],
    "matched_preferred": [],
    "dealbreakers_found": [],
}


def score_job(
    job: dict,
    system_prompt: str,
    log=print,
) -> dict:
    """
    Score a single job using a pre-built system prompt.
    Returns a dict with: score, score_reason, matched_required, matched_preferred, dealbreakers_found.
    """
    user_message = _build_user_message(job)
    client = _get_client()

    response = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_message}],
            )
            break
        except Exception as e:
            if "overloaded" in str(e).lower() and attempt < 2:
                wait = (attempt + 1) * 30
                log(f"  API overloaded, retrying in {wait}s...")
                time.sleep(wait)
            else:
                return {**_ERROR_RESULT, "score_reason": f"API error: {e}"}

    if not response or not response.content:
        return {**_ERROR_RESULT, "score_reason": "Empty response from API"}

    raw = response.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        result = json.loads(raw)
        return {
            "score":              float(result.get("score", 0)),
            "score_reason":       result.get("score_reason", ""),
            "matched_required":   result.get("matched_required", []),
            "matched_preferred":  result.get("matched_preferred", []),
            "dealbreakers_found": result.get("dealbreakers_found", []),
        }
    except json.JSONDecodeError:
        log(f"  Failed to parse Claude response: {raw[:200]}")
        return {**_ERROR_RESULT, "score_reason": "Failed to parse Claude response"}
