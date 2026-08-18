"""CursorBench — cost, tokens and steps per task, always with the effort setting.

This is the only source that publishes what a task actually costs end to end, and the
only one that separates a model from its effort level. Everything downstream leans on it.

The leaderboard is server-rendered as a CSS grid, so each row arrives as one run-together
string: "9Opus 5 High66.7%$3.9127,93248". The regex below is anchored on the two shapes
that cannot collide — a "NN.N%" score and a "$N.NN" cost — and the parser refuses to
return a half-read table rather than reporting a plausible-looking subset.
"""

from __future__ import annotations

import re

from ..htmlparse import text_lines, usd_to_uusd
from ..naming import model_key, split_effort

SOURCE = "cursorbench"
URL = "https://cursor.com/cursorbench"
LABEL = "CursorBench"

# rank | model + effort | score % | $ cost/task | tokens/task | steps/task
#
# The score is bounded to 0.0-100.0 on purpose. Model names end in digits too
# ("Composer 2.5"), so an unbounded number would happily read "Composer 2." + "556.1%"
# out of the same run-together string.
_ROW = re.compile(
    r"^(?P<rank>\d{1,3})"
    r"(?P<model>[A-Za-z].*?)"
    r"(?P<score>100\.0|\d{1,2}\.\d)%"
    r"\$(?P<cost>\d+\.\d{2})"
    r"(?P<tokens>\d{1,3}(?:,\d{3})+|\d{1,3})"
    r"(?P<steps>\d{1,3})$"
)

_VERSION = re.compile(r"CursorBench\s+(\d+\.\d+)")
MIN_ROWS = 10


def parse(raw: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    lines = text_lines(raw)

    for line in lines:
        match = _ROW.match(line)
        if not match:
            continue
        base, effort = split_effort(match["model"])
        key = model_key(base)
        if (key, effort) in seen:
            continue  # the page renders the table twice (desktop + mobile)
        seen.add((key, effort))
        rows.append(
            {
                "model_key": key,
                "effort": effort,
                "rank": int(match["rank"]),
                "score": float(match["score"]),
                "cost_uusd": usd_to_uusd(match["cost"]),
                "tokens": int(match["tokens"].replace(",", "")),
                "steps": int(match["steps"]),
            }
        )

    if len(rows) < MIN_ROWS:
        raise ValueError(f"cursorbench: parsed only {len(rows)} rows — page shape changed")

    version = ""
    for line in lines:
        found = _VERSION.search(line)
        if found:
            version = found.group(1)
            break

    return rows, {"benchmark_version": version, "row_count": len(rows)}


async def fetch(client) -> tuple[list[dict], dict]:
    response = await client.get(URL)
    response.raise_for_status()
    return parse(response.text)
