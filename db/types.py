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
    score: float | None
    score_reason: str


class PreferenceProfile(TypedDict):
    id: int
    content: str
    content_format: str
    applied_count: int
    rejected_count: int
    updated_at: str


class _ProfileSignalRequired(TypedDict):
    type: str
    dim: str


class ProfileSignal(_ProfileSignalRequired, total=False):
    value: str
    conf: str
    n_match: int
    n_total: int
    note: str
