from typing import TypedDict


class JobRow(TypedDict):
    id: str
    title: str
    company: str
    location: str
    url: str
    description: str | None
    source: str
    source_id: str | None
    status: str
    score: float | None
    score_reason: str | None
    rejection_reason: str | None
    created_at: str
    updated_at: str


class JobStats(TypedDict):
    total: int
    new: int
    reviewed: int
    applied: int
    rejected: int
    auto_rejected: int
    avg_score: float | None
    last_run: str | None


class ScoreResult(TypedDict):
    score: float
    score_reason: str
    matched_required: list[str]
    matched_preferred: list[str]
    dealbreakers_found: list[str]


class PreferenceProfile(TypedDict):
    id: int
    content: str
    applied_count: int
    rejected_count: int
    updated_at: str
