import json
import os
import sys
import time
import anthropic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.db.connection import get_connection

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _load_applied_examples():
    conn = get_connection()
    rows = conn.execute("""
        SELECT title, company, description
        FROM examples
        WHERE LENGTH(description) > 100
        LIMIT 8
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _load_rejected_examples():
    conn = get_connection()
    rows = conn.execute("""
        SELECT title, company, description, reasoning
        FROM jobs
        WHERE status = 'rejected'
        AND LENGTH(description) > 100
        AND reasoning IS NOT NULL
        ORDER BY updated_at DESC
        LIMIT 5
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def load_examples():
    """Load few-shot examples from DB. Call once per agent run, pass to evaluate()."""
    return {
        "applied":  _load_applied_examples(),
        "rejected": _load_rejected_examples(),
    }


def _build_examples_section(examples):
    applied  = examples.get("applied", [])
    rejected = examples.get("rejected", [])
    lines = []

    if applied:
        lines.append("EXAMPLES OF JOBS I APPLIED TO (high quality — learn what I like):")
        for ex in applied:
            desc = ex["description"][:200].replace("\n", " ")
            lines.append(f'- "{ex["title"]}" @ {ex["company"]}: {desc}...')
        lines.append("")

    if rejected:
        lines.append("EXAMPLES OF JOBS I REJECTED (learn what to avoid):")
        for ex in rejected:
            desc = ex["description"][:150].replace("\n", " ")
            reason = ex.get("reasoning", "")[:100]
            lines.append(f'- "{ex["title"]}" @ {ex["company"]}: {desc}... [Reason: {reason}]')
        lines.append("")

    return "\n".join(lines) + "\n" if lines else ""


def _build_system_prompt(criteria, examples):
    examples_section = _build_examples_section(examples)

    extra_required = criteria.get('required', [])
    extra_required_section = (
        "\n" + "\n".join(f"- {r}" for r in extra_required)
        if extra_required else ""
    )

    extra_rejected = criteria.get('rejected', [])
    extra_rejected_section = (
        "\n\nADDITIONAL USER-DEFINED REJECTION RULES (reject if any apply):\n"
        + "\n".join(f"- {r}" for r in extra_rejected)
        if extra_rejected else ""
    )

    return f"""You are evaluating job listings for a Senior PHP Engineer based in Poland, working fully remote.

CANDIDATE:
- Senior PHP Engineer, 8+ years experience
- Stack: PHP 8, Symfony, Laravel, Doctrine, MySQL, Docker, Kubernetes, RabbitMQ
- Team Lead and Scrum Master experience
- English C1, Polish citizen, works remotely from Poland
- No visa or work permit needed anywhere — works remotely, never relocates
- Open to: full-time employment, B2B contracts, freelance contracts

{examples_section}REQUIRED (must have all):
- PHP mentioned in the job description — NOTE: Laravel, Symfony, WordPress are PHP frameworks, so they count as PHP
- Remote work possible{extra_required_section}

PREFERRED (increases score):
{"\n".join(f'- {p}' for p in criteria.get('preferred', []))}

AUTOMATIC REJECTION — only reject if the description contains one of these EXACT situations:
1. Candidate must physically relocate or be resident in a specific country
2. Role is on-site with NO remote option
3. Role is junior or intern level
4. Job listing is not in English
5. "Remote, UK based" or "UK based, remote" — means candidate must be in UK
6. "Remote within UK" or "UK remote only" — means candidate must be in UK
7. "Must be eligible to work in the UK" — means physical presence in UK required{extra_rejected_section}

DO NOT reject for:
- Company location ("Berlin-based company", "Paris-based startup", "London HQ")
- "Germany (Remote)", "UK (Remote)", "France (Remote)" in location field — these mean remote IS available
- Visa sponsorship mentions — candidate works remotely from Poland, needs no visa anywhere
- Work authorization mentions — same reason
- "United States (Remote)", "Canada (Remote)" — remote from Poland is fine
- "EMEA" region — Poland is in EMEA, so EMEA-restricted roles are fine for this candidate
- "Europe" region — Poland is in Europe, so Europe-restricted roles are fine

Respond ONLY with JSON, no other text:
{{
    "score": <0-10>,
    "reasoning": "<one sentence>",
    "matched_required": [],
    "matched_preferred": [],
    "dealbreakers_found": []
}}"""


def _build_user_message(job):
    return (
        f"Evaluate this job:\n\n"
        f"Title: {job['title']}\n"
        f"Company: {job['company']}\n"
        f"Location: {job['location']}\n"
        f"Description: {job['description'][:3000]}"
    )


def evaluate(job, criteria=None, examples=None):
    if criteria is None:
        from src.db.repositories.criteria_repository import get_criteria_dict
        criteria = get_criteria_dict()
    if examples is None:
        examples = load_examples()

    system_prompt = _build_system_prompt(criteria, examples)
    user_message  = _build_user_message(job)

    for attempt in range(3):
        try:
            response = _get_client().messages.create(
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
                print(f"  API overloaded, retrying in {wait}s...")
                time.sleep(wait)
            else:
                return {
                    "score":              0.0,
                    "reasoning":          f"API error: {e}",
                    "matched_required":   [],
                    "matched_preferred":  [],
                    "dealbreakers_found": [],
                }

    raw = response.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        result = json.loads(raw)
        return {
            "score":              float(result.get("score", 0)),
            "reasoning":          result.get("reasoning", ""),
            "matched_required":   result.get("matched_required", []),
            "matched_preferred":  result.get("matched_preferred", []),
            "dealbreakers_found": result.get("dealbreakers_found", []),
        }
    except json.JSONDecodeError:
        print(f"Raw response: {raw}")
        return {
            "score":              0.0,
            "reasoning":          "Failed to parse Claude response",
            "matched_required":   [],
            "matched_preferred":  [],
            "dealbreakers_found": [],
        }


if __name__ == "__main__":
    test_job = {
        "title": "Senior PHP Developer",
        "company": "Test Company",
        "location": "Germany (Remote)",
        "description": """
            We are looking for a Senior PHP Developer with 5+ years of experience.
            You will work on our SaaS B2B platform using PHP 8, Symfony, Docker, Kubernetes.
            Requirements: PHP, Symfony, MySQL, clean code, SOLID principles.
            Nice to have: RabbitMQ, Redis, experience with microservices.
            100% remote, English-speaking team.
        """
    }

    print("Testing evaluator...")
    result = evaluate(test_job)
    print(f"Score: {result['score']}/10")
    print(f"Reasoning: {result['reasoning']}")
    print(f"Matched required: {result['matched_required']}")
    print(f"Matched preferred: {result['matched_preferred']}")
    print(f"Dealbreakers: {result['dealbreakers_found']}")
