"""Artificial Analysis — quality, cost and the clock, per model and per effort.

The source everything on the board is scored by. Artificial Analysis runs every model through
the same ten evaluations (its Intelligence Index), on its own hardware, and publishes for each
variant at each effort setting: the index score, what one task of the index cost, how many
tokens it produced, how fast it typed and how long you waited before the first answer token.
One source for quality, price and time means the three are measured on the same runs — the
join that used to take two sites and an effort-lending rule is now one record.

Where the numbers are. Everything is in the pages' React Server Components payload — the
`self.__next_f.push([1, "…"])` scripts Next.js streams a page with — and never in the JSON-LD,
which carries only the top twenty of each chart. Until 7 October 2026 every model page carried
all ~665 variants. Since then the data is in two places:

- The leaderboard (`/leaderboards/models`) carries every variant in one flat table: score, cost
  per task, speed, the wait to the first answer. One request, read on every run.
- A variant's own page (`/models/<slug>`) carries the full record: the release name and the
  effort slug that identify it, the release date, the tokens and the time per task. The
  leaderboard has none of those, and time per task is what patience is measured in.

So a run reads the leaderboard, and reads a variant page only when the archive cannot answer
for it: a slug never seen before, or a priced variant whose score or cost moved — new runs
mean a new time. Everything else keeps the identity and the clock it was archived with. A
fresh database reads every page once; after that a run reads a handful.

Both payloads are an implementation detail of their site, not an API (their free API has no
cost or time per task), so the parser refuses to return a half-read table: fewer records than
MIN_ROWS, or fewer priced ones than MIN_PRICED, means the page changed shape and the last good
reading stays on screen. A variant page that does not answer fails the run for the same reason.
"""

from __future__ import annotations

import asyncio
import json
import os
import re

from ..htmlparse import usd_to_uusd
from ..naming import model_key, split_effort, vendor_of

SOURCE = "artificialanalysis"
URL = os.environ.get(
    "KVASIR_AA_BOARD_URL", "https://artificialanalysis.ai/leaderboards/models"
)
SITE_URL = "https://artificialanalysis.ai/models"
LABEL = "Artificial Analysis"

MIN_ROWS = 200
MIN_PRICED = 50
# Between two variant pages. Only a fresh database reads many; be a polite guest anyway.
PAGE_PAUSE_S = 0.5

_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
# A model record opens with its id and its slug, in that order. Creators and releases open
# the same way but carry no index score, which is how they are told apart below. Slugs are not
# all lowercase kebab: "qwen3-0.6b-instruct", "QwQ-32B-Preview".
_RECORD = re.compile(r'\{"id":"[0-9a-f-]{36}","slug":"[A-Za-z0-9.-]+"')
_VERSION = re.compile(r"Intelligence Index v(\d+(?:\.\d+)?)")
# The leaderboard table opens with this key; nothing else on the page does.
_BOARD = '{"models":['
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


def _measured(entry: dict) -> dict:
    """The numbers a leaderboard entry carries, named as _row() names them.

    Checked against the variant pages when the leaderboard became the source: the same
    figures to the last rounded digit.
    """
    cost = _num(entry.get("intelligenceIndexCostPerTask"))
    terminal = _num(entry.get("terminalBench40"))
    return {
        "source_name": entry["name"],
        "score": _round(_num(entry.get("intelligenceIndex"))),
        "cost_uusd": usd_to_uusd(cost),
        "terminal_bench": _round(terminal * 100) if terminal is not None else None,
        "tokens_per_second": _round(_num(entry.get("medianOutputTokensPerSecond"))),
        "first_answer_seconds": _round(_num(entry.get("medianTimeToFirstAnswerTokenSeconds")) or None),
        "thinking_seconds": _round(_num(entry.get("medianReasoningTimeSeconds")) or None),
        "end_to_end_seconds": _round(_num(entry.get("medianEndToEndResponseTimeSeconds")) or None),
        "deprecated": bool(entry.get("deprecated")),
    }


def parse_board(raw: str) -> list[dict]:
    """Every variant on the leaderboard, as the raw entries of its table."""
    stream = _payload(raw)
    start = stream.find(_BOARD)
    board: list[dict] = []
    if start >= 0:
        try:
            table, _ = json.JSONDecoder().raw_decode(stream, start)
            board = [
                entry
                for entry in table["models"]
                if isinstance(entry, dict) and entry.get("slug") and "intelligenceIndex" in entry
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            board = []
    priced = sum(1 for entry in board if _num(entry.get("intelligenceIndexCostPerTask")) is not None)
    if len(board) < MIN_ROWS or priced < MIN_PRICED:
        raise ValueError(
            f"artificialanalysis: read {len(board)} variants, {priced} priced — page shape changed"
        )
    return board


def parse_variant(raw: str, slug: str) -> tuple[dict, str]:
    """The full record of one variant, from its own page, and the index version it names."""
    record = _records(_payload(raw)).get(slug)
    if record is None:
        raise ValueError(f"artificialanalysis: no record for {slug} on its own page")
    version = _VERSION.search(raw)
    return _row(record), version.group(1) if version else ""


def needs_page(entry: dict, known: dict | None, folded: bool = False) -> bool:
    """Whether the archive cannot answer for this variant, so its own page must be read.

    `folded` is a variant that lost the (model, effort) fold to a shorter slug: its identity
    is archived, and nothing else of it is ever shown.
    """
    if folded:
        return False
    if known is None:
        return True
    fresh = _measured(entry)
    if fresh["cost_uusd"] is None:
        return False  # identity is archived; an unpriced variant has no clock to keep fresh
    moved = (fresh["score"], fresh["cost_uusd"]) != (known.get("score"), known.get("cost_uusd"))
    return moved or known.get("task_seconds") is None


def fold(rows: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """One row per (model, effort), and the variants that lost, by slug.

    Two variants can fold into one (model, effort) — a "(Preview)" beside the release, or two
    non-reasoning modes. The shortest slug is the site's own canonical page for it.
    """
    by_variant: dict[tuple[str, str], dict] = {}
    losers: dict[str, dict] = {}
    for row in rows:
        variant = (row["model_key"], row["effort"])
        held = by_variant.get(variant)
        if held is None or len(row["source_slug"]) < len(held["source_slug"]):
            if held is not None:
                losers[held["source_slug"]] = held
            by_variant[variant] = row
        else:
            losers[row["source_slug"]] = row
    return list(by_variant.values()), losers


def merge(
    board: list[dict],
    known: dict[str, dict],
    folded: dict[str, dict],
    pages: dict[str, dict],
    version: str,
) -> tuple[list[dict], dict]:
    """The board: identity and clock from a page or the archive, numbers from the leaderboard.

    The variants that lose the fold are kept in `folded`, so the next run knows them without
    reading their pages.
    """
    merged = []
    for entry in board:
        slug = entry["slug"]
        base = pages.get(slug) or known.get(slug)
        if base is None and slug in folded:
            # Only its identity was archived. Should it ever win the fold, it has no clock yet,
            # and the next run reads its page because the archive now holds it untimed.
            base = {"output_tokens": None, "task_seconds": None, **folded[slug]}
        if base is None:
            raise ValueError(f"artificialanalysis: {slug} has no record — page not read")
        merged.append({**base, **_measured(entry), "source_slug": slug})
    rows, losers = fold(merged)
    priced = sum(1 for row in rows if row["cost_uusd"] is not None)
    return rows, {
        "benchmark_version": version,
        "row_count": len(rows),
        "priced_count": priced,
        "folded": {
            slug: {key: row[key] for key in ("model_key", "effort", "vendor", "released")}
            for slug, row in sorted(losers.items())
        },
    }


async def fetch(client) -> tuple[list[dict], dict]:
    from .. import db
    from ..config import settings

    response = await client.get(URL, follow_redirects=True)
    response.raise_for_status()
    board = parse_board(response.text)

    archived, meta = db.latest(settings.db_path, SOURCE)
    known = {row["source_slug"]: row for row in archived if row.get("source_slug")}
    folded = meta.get("folded") or {}
    version = meta.get("benchmark_version") or ""
    pages: dict[str, dict] = {}
    for entry in board:
        slug = entry["slug"]
        if not needs_page(entry, known.get(slug), slug in folded):
            continue
        page = await client.get(f"{SITE_URL}/{slug}", follow_redirects=True)
        page.raise_for_status()
        pages[slug], page_version = parse_variant(page.text, slug)
        # A new index version re-scores every variant, so the pages carry it in.
        version = page_version or version
        await asyncio.sleep(PAGE_PAUSE_S)
    return merge(board, known, folded, pages, version)
