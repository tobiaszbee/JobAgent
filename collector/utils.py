from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str | None:
        return " ".join(" ".join(self._parts).split()).strip() or None


def strip_html(html: str) -> str | None:
    """Strip HTML tags and return clean text, or None for empty input."""
    if not html or not html.strip():
        return None
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.text()
