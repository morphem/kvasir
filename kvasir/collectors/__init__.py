"""Source collectors.

Each collector is a module with three things:

    SOURCE  — stable id, also the key used in the database and the API
    URL     — where the data comes from, shown in the UI next to every number
    parse() — pure function from raw response text to (rows, meta)
    fetch() — network wrapper around parse()

Keeping parse() pure is what makes the parsers testable against the saved fixtures in
tests/fixtures/, which is the only defence against a source silently changing shape.
"""

from __future__ import annotations

from . import copilot, cursorbench, stupidlevel

MODULES = {m.SOURCE: m for m in (cursorbench, stupidlevel, copilot)}

SOURCE_LABELS = {
    "cursorbench": "CursorBench",
    "stupidlevel": "AI Stupid Level",
    "copilot": "GitHub Copilot",
}

__all__ = ["MODULES", "SOURCE_LABELS", "copilot", "cursorbench", "stupidlevel"]
