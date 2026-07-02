from collector.sources.linkedin import LinkedInSource
from collector.sources.justjoin import JustJoinSource

_REGISTRY: dict[str, dict] = {
    "linkedin": {"name": "LinkedIn", "cls": LinkedInSource},
    "justjoin": {"name": "JustJoin.it", "cls": JustJoinSource},
}


def available() -> list[dict]:
    return [{"id": k, "name": v["name"]} for k, v in _REGISTRY.items()]


def make(source_id: str, **kwargs):
    entry = _REGISTRY.get(source_id)
    if not entry:
        raise ValueError(f"Unknown source: {source_id!r}")
    return entry["cls"](**kwargs)
