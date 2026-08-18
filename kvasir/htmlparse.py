"""Two tiny HTML readers, built on the standard library.

Both sources we scrape are documentation-shaped pages, not APIs, so the parsers are
deliberately dumb: GitHub's page is real <table> markup, and CursorBench's leaderboard is
a CSS grid whose numbers only exist as text. Pulling in a parser library to read them
would not make either one less brittle.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# <sup> carries GitHub's footnote markers, which otherwise glue a stray digit to a
# model name ("Gemini 3.6 Flash1").
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "sup"}


class _TableReader(HTMLParser):
    """Collects every <table> on the page as a list of rows of cell text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(_squash("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._skip == 0 and self._cell is not None:
            self._cell.append(data)


class _TextReader(HTMLParser):
    """Flattens a page to visible text, one newline per block-level element."""

    _BLOCK = {"div", "p", "tr", "li", "section", "h1", "h2", "h3", "h4", "table", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def tables(html: str) -> list[list[list[str]]]:
    reader = _TableReader()
    reader.feed(html)
    return reader.tables


def text_lines(html: str) -> list[str]:
    reader = _TextReader()
    reader.feed(html)
    joined = "".join(reader.parts)
    return [_squash(line) for line in joined.split("\n") if _squash(line)]


def usd_to_uusd(value: str | float) -> int | None:
    """Money is stored as integer micro-dollars — never as a float.

    Same reason the ecosystem stores PLN in grosze: these numbers get summed, averaged
    and diffed across months of snapshots, and float dollars drift while doing it.
    """
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
            return None
        value = float(cleaned)
    return int(round(float(value) * 1_000_000))
