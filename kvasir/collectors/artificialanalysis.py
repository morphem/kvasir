"""Artificial Analysis — quality, cost and the clock, per model and per effort.

The source everything on the board is scored by. Artificial Analysis runs every model through
the same ten evaluations (its Intelligence Index), on its own hardware, and publishes for each
variant at each effort setting: the index score, what one task of the index cost, how many
tokens it produced, how fast it typed and how long you waited before the first answer token.
One source for quality, price and time means the three are measured on the same runs — the
join that used to take two sites and an effort-lending rule is now one record.

Where the numbers are. The JSON-LD blocks on the page carry only the top twenty of each chart,
which is why a third of our board used to have "no speed". The full table is in the page's
React Server Components payload — the `self.__next_f.push([1, "…"])` scripts Next.js streams
the page with. Every model page carries the whole set (665 variants in September 2026), so the
URL is an entry point, not a subject. Each variant is one plain JSON object that starts with
its id and slug; we find those, decode them with the standard library, and ignore the rest of
the payload.

That payload is an implementation detail of their site, not an API, so the parser refuses to
return a half-read table: fewer records than MIN_ROWS, or fewer priced ones than MIN_PRICED,
means the page changed shape and the last good reading stays on screen.
"""

from __future__ import annotations

import json
import os
import re

from ..htmlparse import usd_to_uusd
from ..naming import model_key, split_effort, vendor_of

SOURCE = "artificialanalysis"
URL = os.environ.get("KVASIR_AA_URL", "https://artificialanalysis.ai/models/claude-opus-5-5")
SITE_URL = "https://artificialanalysis.ai/models"
LABEL = "Artificial Analysis"

MIN_ROWS = 200
MIN_PRICED = 50

_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
# A model record opens with its id and its slug, in that order. Creators and releases open
# the same way but carry no index score, which is how they are told apart below.
_RECORD = re.compile(r'\{"id":"[0-9a-f-]{36}","slug":"[a-z0-9-]+"')
_VERSION = re.compile(r"Intelligence Index v(\d+(?:\.\d+)?)")
# "Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default)" -> "Claude Opus 5.5"
_QUALIFIER = re.compile(r"\s*\(.*\)\s*$")


def _payload(raw: str) -> str:
    """The RSC stream, reassembled. Each chunk is a JavaScript string literal."""
    parts = []
    for chunk in _CHUNK.findall(raw):
        try:
            parts.append(json.loads(f'"{chunk}"'))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def _records(stream: str) -> dict[str, dict]:
    decoder = json.JSONDecoder()
    found: dict[str, dict] = {}
    for match in _RECORD.finditer(stream):
        try:
            record, _ = decoder.raw_decode(stream, match.start())
        except json.JSONDecodeError:
            continue
        if "intelligenceIndex" in record:
            found.setdefault(record["slug"], record)
    return found


def _effort(record: dict) -> str:
    """The effort this variant ran at, on our ladder.

    A non-reasoning variant is not "low effort", it is a different mode, so it gets no effort
    at all — and the board never shows a number without one.
    """
    slug = (record.get("effort") or {}).get("slug")
    if not record.get("isReasoning") or not slug:
        return "default"
    return split_effort(f"model {slug}")[1]


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def _row(record: dict) -> dict:
    name = (record.get("release") or {}).get("name") or _QUALIFIER.sub("", record["name"])
    key = model_key(name)
    cost = _num(((record.get("intelligenceIndexCostPerTask") or {}).get("cost") or {}).get("total"))
    tokens = _num((record.get("intelligenceIndexOutputTokensPerTask") or {}).get("output"))
    first_answer = record.get("timeToFirstAnswerToken") or {}
    terminal = _num(record.get("terminalBench40"))
    # "Weighted average decode time per task; excludes TTFT and overhead time" — in seconds in
    # the record (their chart shows minutes). Measured in the same runs as the score and the
    # cost, so every priced variant has one: it is how long one loop of an agent takes.
    task_seconds = _num(record.get("intelligenceIndexTimePerTask"))
    return {
        "model_key": key,
        "effort": _effort(record),
        "vendor": vendor_of(key),
        "source_name": record["name"],
        "source_slug": record["slug"],
        "score": _round(_num(record.get("intelligenceIndex"))),
        "cost_uusd": usd_to_uusd(cost),
        "output_tokens": round(tokens) if tokens is not None else None,
        "terminal_bench": _round(terminal * 100) if terminal is not None else None,
        "tokens_per_second": _round(
            _num((record.get("timescaleData") or {}).get("medianOutputSpeed"))
        ),
        # A zero here is an empty bar, not an instant answer — absent is absent.
        "first_answer_seconds": _round(_num(first_answer.get("total")) or None),
        "thinking_seconds": _round(_num(first_answer.get("reasoning")) or None),
        "end_to_end_seconds": _round(
            _num((record.get("endToEndResponseTime") or {}).get("total")) or None
        ),
        "task_seconds": _round(task_seconds or None),
        "deprecated": bool(record.get("deprecated")),
        "released": record.get("releaseDate") or "",
    }


def parse(raw: str) -> tuple[list[dict], dict]:
    records = _records(_payload(raw))

    # Two variants can fold into one (model, effort) — a "(Preview)" beside the release, or two
    # non-reasoning modes. The shortest slug is the site's own canonical page for it.
    by_variant: dict[tuple[str, str], tuple[str, dict]] = {}
    for slug, record in records.items():
        row = _row(record)
        variant = (row["model_key"], row["effort"])
        held = by_variant.get(variant)
        if held is None or len(slug) < len(held[0]):
            by_variant[variant] = (slug, row)
    rows = [row for _, row in by_variant.values()]

    priced = sum(1 for row in rows if row["cost_uusd"] is not None)
    if len(rows) < MIN_ROWS or priced < MIN_PRICED:
        raise ValueError(
            f"artificialanalysis: read {len(rows)} variants, {priced} priced — page shape changed"
        )

    version = _VERSION.search(raw)
    return rows, {
        "benchmark_version": version.group(1) if version else "",
        "row_count": len(rows),
        "priced_count": priced,
    }


async def fetch(client) -> tuple[list[dict], dict]:
    response = await client.get(URL, follow_redirects=True)
    response.raise_for_status()
    return parse(response.text)
