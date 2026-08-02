"""Shared location-matching logic for API-based job sources."""


def workplace_suffix(modes: set[str]) -> str:
    """Build a "(Remote)"/"(Hybrid)"/"" location-string suffix from a normalized
    set of workplace-mode tokens ("remote", "hybrid", "onsite") reported by a
    Polish job board. Callers translate their own site-specific vocabulary
    (Polish or English, single value or list) into this common set before
    calling. An offer can legitimately advertise more than one mode (e.g.
    "hybrid or fully remote") — remote wins the label since it's the strictest
    claim a downstream geo check needs to be able to trust."""
    if "remote" in modes:
        return " (Remote)"
    if "hybrid" in modes:
        return " (Hybrid)"
    return ""

_EU_COUNTRIES = frozenset({
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic",
    "denmark", "estonia", "finland", "france", "germany", "greece", "hungary",
    "ireland", "italy", "latvia", "liechtenstein", "lithuania", "luxembourg",
    "malta", "netherlands", "norway", "poland", "portugal", "romania",
    "slovakia", "slovenia", "spain", "sweden", "switzerland", "united kingdom",
})

_WORLDWIDE_TOKENS = frozenset({"worldwide", "anywhere", "global", "international"})
_EUROPE_TOKENS    = frozenset({"europe", "european", "emea", "eea", "eu "})
_NA_TOKENS        = frozenset({"north america", "usa/canada", "canada/usa", "americas"})

_COUNTRY_ALIASES: dict[str, str] = {
    "us":            "united states",
    "usa":           "united states",
    "u.s.":          "united states",
    "uk":            "united kingdom",
    "gb":            "united kingdom",
    "great britain": "united kingdom",
    "deutschland":   "germany",
    "polska":        "poland",
    "pl":            "poland",
}

_REMOTE_TERMS = frozenset({"remote", "zdalne", "zdalnie", "zdalny"})

# Timezone abbreviations that indicate a Central/Western/Eastern Europe work schedule.
# "Time zone: CET (+/- 3 hours)" and "CET (+/- 3 hours)" are used by WorkingNomads.
_EU_TIMEZONE_TOKENS = frozenset({"cet", "cest", "eet", "eest", "wet", "west"})


def location_matches(job_location: str, search_location: str) -> bool:
    job_required_location = job_location.lower()
    raw_search = search_location.lower().strip()
    normalized_search = _COUNTRY_ALIASES.get(raw_search, raw_search)

    if normalized_search in _REMOTE_TERMS:
        return True
    if not job_required_location or any(t in job_required_location for t in _WORLDWIDE_TOKENS):
        return True
    if normalized_search in _EU_COUNTRIES and any(t in job_required_location for t in _EUROPE_TOKENS):
        return True
    if normalized_search in _EU_COUNTRIES and any(t in job_required_location for t in _EU_TIMEZONE_TOKENS):
        return True
    if normalized_search in ("united states", "canada") and any(t in job_required_location for t in _NA_TOKENS):
        return True
    if normalized_search in job_required_location:
        return True
    aliases = [k for k, v in _COUNTRY_ALIASES.items() if v == normalized_search]
    return any(a in job_required_location for a in aliases)
