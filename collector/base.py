from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RawJob:
    title: str
    company: str
    location: str
    url: str
    source: str
    source_id: str | None = None
    description: str | None = None


class JobSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def search(self, title: str, location: str, days_back: int, max_results: int | None = None) -> list[RawJob]: ...

    def fetch_description(self, url: str) -> str | None:
        """Override in sources that can fetch full job descriptions."""
        return None
