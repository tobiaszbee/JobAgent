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
