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

from . import artificialanalysis, copilot, stupidlevel

MODULES = {m.SOURCE: m for m in (artificialanalysis, stupidlevel, copilot)}

SOURCE_LABELS = {
    "artificialanalysis": "Artificial Analysis",
    "stupidlevel": "AI Stupid Level",
    "copilot": "GitHub Copilot",
}

# Sources that are no longer polled but whose readings stay in the archive. CursorBench scored
# the board until 2026-09-22 and the old speed reader timed it; their snapshots remain readable
# through /api/history, because a number the page once showed must stay findable.
RETIRED_SOURCES = {"cursorbench": "CursorBench", "speed": "Artificial Analysis (JSON-LD speed)"}

__all__ = ["MODULES", "RETIRED_SOURCES", "SOURCE_LABELS", "artificialanalysis", "copilot", "stupidlevel"]
