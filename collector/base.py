from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawJob:
    title: str
    company: str
    location: str
    url: str
    source: str
    source_id: str | None = None
    description: str | None = None
    # ISO 8601 string, not a datetime — every source that parses one already does
    # so to apply days_back, and isoformat() is what job_repository.insert sends
    # over the API as-is. None for sources with no reliable per-posting date
    # (LinkedIn shows only relative text like "2 days ago" in its UI).
    posted_at: str | None = None


class JobSource(ABC):
    requires_stealth_pauses: bool = False

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def search(self, title: str, location: str, days_back: int | None = None, max_results: int | None = None, known_urls: set[str] | None = None) -> list[RawJob]: ...

    def fetch_description(self, url: str) -> str | None:
        """Override in sources that can fetch full job descriptions."""
        return None

    def login(self) -> None:
        """Override in sources that require authentication."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass
