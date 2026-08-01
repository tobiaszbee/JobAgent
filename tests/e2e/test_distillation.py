"""
End-to-end distillation tests: preference_agent round-trip with real API.

Run with:  pytest -m e2e
Skipped unless a real ANTHROPIC_API_KEY is set.

Test scenarios:
  D-1: Full distillation returns non-empty signals list with valid types
  D-2: stop_reason == end_turn (output not truncated)
  D-3: Strong rejection pattern captured (5/5 rejected = agency → REJECT signal present)
  D-4: No location signals in profile (filtered upstream)
  D-5: Round-trip: distilled profile steers scorer (product job >> agency job by >= 2 pts)
"""
import os
import pytest

from db.repositories import job_repository, cv_repository, criteria_repository
from preference_agent.runner import run as run_distillation, _build_prompt, _SYSTEM
from preference_agent.profile import _DISTILL_TOOL, render_signals
from evaluator.scorer import build_system_prompt, score_job

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("ANTHROPIC_API_KEY", "test-").startswith("test-"),
        reason="Requires real ANTHROPIC_API_KEY",
    ),
]

_CV_PARSED = {
    "seniority": "Senior",
    "years_experience": 8,
    "stack": ["PHP", "Symfony", "Docker", "PostgreSQL"],
    "location": "Poland",
    "remote_preference": "fully remote",
    "raw_summary": (
        "Backend engineer with 8 years in PHP/Symfony, building scalable SaaS platforms. "
        "Prefers product companies, async remote culture, B2B contracts. "
        "Avoids agencies, outstaffing, and on-site roles."
    ),
}

_CRITERIA = {
    "required": ["PHP", "remote"],
    "preferred": ["Symfony", "B2B", "startup"],
    "rejected": ["junior", "intern"],
    "location": ["Europe", "Remote"],
    "search_query": ["PHP Developer"],
}

_APPLIED_JOBS = [
    {
        "title": "Senior PHP Developer", "company": "ProductCo", "location": "Remote",
        "source": "remoteok", "url": "https://productco.example/jobs/1",
        "description": (
            "Product SaaS company, B2B contract, async remote culture. "
            "Symfony, Docker, PostgreSQL. Competitive rate 130 EUR/h published upfront."
        ),
    },
    {
        "title": "Backend Engineer PHP", "company": "SaaSStartup", "location": "Remote Europe",
        "source": "remoteok", "url": "https://saas.example/jobs/2",
        "description": (
            "Growing SaaS startup, fully remote, B2B. PHP 8.2, Symfony 7. "
            "Rate 120-150 EUR/h posted in offer. Small async team."
        ),
    },
    {
        "title": "PHP/Symfony Engineer", "company": "TechProduct", "location": "Remote (EU)",
        "source": "linkedin", "url": "https://techproduct.example/jobs/3",
        "description": (
            "Fully remote product company building analytics platform. "
            "PHP, Symfony 6, async team, no micromanagement. B2B preferred. Rate visible."
        ),
    },
]

_REJECTED_JOBS = [
    {
        "title": "PHP Developer", "company": "AgencyCo", "location": "Remote",
        "source": "linkedin", "url": "https://agencyco.example/jobs/1",
        "description": "Outsourcing company, client-based projects. Rate negotiable (not published).",
        "rejection_reason": "agency/outstaffing model, no rate published",
    },
    {
        "title": "PHP Backend Developer", "company": "Staffing Solutions", "location": "Worldwide",
        "source": "remoteok", "url": "https://staffing.example/jobs/2",
        "description": "IT staffing company. You will work on client sites. Body shop model.",
        "rejection_reason": "staffing agency, body shop",
    },
    {
        "title": "Symfony Developer", "company": "BodyShop Ltd", "location": "Remote",
        "source": "remotive", "url": "https://bodyshop.example/jobs/3",
        "description": "We connect developers with clients worldwide. Outstaffing model.",
        "rejection_reason": "outstaffing, rate unknown",
    },
    {
        "title": "PHP Engineer", "company": "OutstaffingPro", "location": "Remote",
        "source": "remoteok", "url": "https://outstaffing.example/jobs/4",
        "description": "Join our developer pool. We place you with clients. Rate: market rate.",
        "rejection_reason": "outstaffing model",
    },
    {
        "title": "Backend PHP Developer", "company": "ITAgency", "location": "Remote",
        "source": "linkedin", "url": "https://itagency.example/jobs/5",
        "description": "IT agency focused on client delivery. PHP, various stacks. Rate at interview.",
        "rejection_reason": "agency, rate hidden",
    },
]


@pytest.fixture(autouse=True)
def distillation_fixtures():
    cv_repository.insert("test_cv.pdf", "Senior PHP developer CV", _CV_PARSED)
    for criteria_type, values in _CRITERIA.items():
        for value in values:
            criteria_repository.insert(criteria_type, value)

    for job in _APPLIED_JOBS:
        job_id = job_repository.insert(
            title=job["title"], company=job["company"], location=job["location"],
            url=job["url"], source=job["source"], description=job["description"],
        )
        job_repository.update_status(job_id, "applied")

    for job in _REJECTED_JOBS:
        job_id = job_repository.insert(
            title=job["title"], company=job["company"], location=job["location"],
            url=job["url"], source=job["source"], description=job["description"],
        )
        job_repository.update_status(job_id, "rejected", rejection_reason=job["rejection_reason"])


_VALID_TYPES = {"ACCEPT", "REJECT", "INFER", "NEUTRAL"}


class TestDistillation:
    def test_produces_valid_profile_format(self):
        result = run_distillation()
        assert result["ok"], f"Distillation failed: {result}"
        signals = result["signals"]
        assert signals, "Expected non-empty signals list"
        for s in signals:
            assert s.get("type") in _VALID_TYPES, f"Invalid signal type: {s}"
            assert s.get("dim"), f"Signal missing dim: {s}"

    def test_stop_reason_is_end_turn(self):
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

        applied, rejected = job_repository.get_all_feedback()
        stats = job_repository.get_stats()
        prompt = _build_prompt(applied, rejected, stats["applied"], stats["rejected"])
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[_DISTILL_TOOL],
            tool_choice={"type": "tool", "name": "submit_profile"},
        )
        assert response.stop_reason != "max_tokens", (
            f"Profile output was truncated (stop_reason={response.stop_reason!r})"
        )

    def test_captures_agency_rejection_signal(self):
        """5/5 rejected jobs are agencies — profile must contain a REJECT for agency/staffing."""
        result = run_distillation()
        assert result["ok"]
        rejects = [s for s in result["signals"] if s.get("type") == "REJECT"]
        agency_values = {"agency", "outstaffing", "staffing", "body_shop", "outsourcing"}
        found = any(
            any(kw in (s.get("value") or "").lower() or kw in (s.get("note") or "").lower()
                for kw in agency_values)
            for s in rejects
        )
        assert found, (
            f"Expected agency rejection signal in signals:\n{result['signals']}"
        )

    def test_no_location_signals_in_profile(self):
        result = run_distillation()
        assert result["ok"]
        rendered = render_signals(result["signals"]).lower()
        # "remote" is allowed as a work_culture value (async_remote, remote-first);
        # check only hard geographic/legal signals that should never appear
        geo_keywords = ["poland", "europe", "visa", "geography", "citizenship", "on-site", "onsite"]
        for kw in geo_keywords:
            assert kw not in rendered, (
                f"Geographic signal '{kw}' found in profile (should be filtered upstream):\n{rendered}"
            )

    def test_round_trip_profile_steers_scoring(self):
        """Distilled agency-rejection profile should score product company >> agency."""
        distil_result = run_distillation()
        assert distil_result["ok"]
        signals = distil_result["signals"]

        criteria = criteria_repository.get_active_dict()
        from evaluator.profile import load_active_profile
        cv_profile = load_active_profile()

        system_prompt = build_system_prompt(criteria, [], [], cv_profile, signals)

        product_job = {
            "title": "Senior PHP Developer",
            "company": "ProductCo",
            "location": "Remote",
            "description": (
                "Product SaaS company. PHP, Symfony, B2B contract, fully remote async culture. "
                "Rate 130 EUR/h published. No agency model, building own product."
            ),
        }
        agency_job = {
            "title": "PHP Developer",
            "company": "OutstaffCo",
            "location": "Remote",
            "description": (
                "IT outsourcing agency. We place you with clients worldwide. "
                "PHP projects, various stacks. Rate negotiable (agency takes a cut)."
            ),
        }

        product_score = score_job(product_job, system_prompt)
        agency_score = score_job(agency_job, system_prompt)

        assert product_score["score"] is not None, "Product job scoring failed"
        assert agency_score["score"] is not None, "Agency job scoring failed"
        assert product_score["score"] - agency_score["score"] >= 2, (
            f"Product ({product_score['score']}) should outscore agency ({agency_score['score']}) "
            f"by >= 2 pts.\nProduct reason: {product_score['score_reason']}\n"
            f"Agency reason: {agency_score['score_reason']}"
        )
