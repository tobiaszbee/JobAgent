from collector.sources.linkedin import LinkedInSource
from collector.sources.justjoin import JustJoinSource
from collector.sources.remotive import RemotiveSource
from collector.sources.remoteok import RemoteOKSource
from collector.sources.workingnomads import WorkingNomadsSource

_REGISTRY: dict[str, dict] = {
    "linkedin":      {"name": "LinkedIn",        "cls": LinkedInSource},
    "justjoin":      {"name": "JustJoin.it",     "cls": JustJoinSource},
    "remotive":      {"name": "Remotive.io",     "cls": RemotiveSource},
    "remoteok":      {"name": "Remote OK",       "cls": RemoteOKSource},
    "workingnomads": {"name": "Working Nomads",  "cls": WorkingNomadsSource},
}


def available() -> list[dict]:
    return [{"id": k, "name": v["name"]} for k, v in _REGISTRY.items()]


def make(source_id: str, **kwargs):
    entry = _REGISTRY.get(source_id)
    if not entry:
        raise ValueError(f"Unknown source: {source_id!r}")
    return entry["cls"](**kwargs)
