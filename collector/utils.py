import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        self._fragments.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._fragments.append("\n")

    def to_text(self) -> str | None:
        joined = "".join(self._fragments)
        lines = [" ".join(line.split()) for line in joined.split("\n")]
        result = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return result or None


def strip_html(html: str) -> str | None:
    if not html or not html.strip():
        return None
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.to_text()


# LinkedIn appends page chrome after the real job text (footer links, "people also
# viewed", pagination) — cut at the earliest of these markers. Other sources don't
# have this pattern and pass through unchanged.
_LINKEDIN_JUNK_MARKERS = (
    "Set alert for similar jobs", "Accessibility", "People also viewed",
    "Similar jobs", "Show more", "Show less",
)

# Safety-net cap for every LLM/embedding call that reads a job description —
# real postings rarely approach this even after allowing for the full text, so
# in practice this is a backstop against a pathological outlier, not a real trim.
_MAX_DESCRIPTION_CHARS = 6000


def strip_description_junk(description: str, source: str) -> str:
    if source != "linkedin" or not description:
        return description
    cut = len(description)
    for marker in _LINKEDIN_JUNK_MARKERS:
        idx = description.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return description[:cut].rstrip()


def build_excerpt(description: str | None, source: str) -> str:
    """Cleaned, capped description text for LLM/embedding input. Every consumption
    point (scorer, reranker, listwise, debate) should go through this rather than
    reading job['description'] directly, so junk-stripping and the length cap stay
    consistent everywhere instead of each call site picking its own ad-hoc limit."""
    if not description:
        return ""
    cleaned = strip_description_junk(description, source)
    return cleaned[:_MAX_DESCRIPTION_CHARS]
