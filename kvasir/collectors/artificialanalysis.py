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

Since 14 November 2026 the leaderboard entries carry no slug, only the record `id` and the
release (`release.slug`), and a variant URL redirects to its release's page, which holds the
full record of every variant of that release. So an entry is identified by its `id`: from
the archive when the variant is known, otherwise from its release page, read once for all
its variants. The entry also carries the time per task now, the clock patience runs on.

The same day the table shrank from ~700 variants to the ~280 current ones: a release the
site no longer lists, like Gemini 3.8 Flash, is still scored on its own page. A model that
Copilot sells and the table dropped is read from that page (`off_board`), so what we can
start does not fall off the board because the site tidied its table.

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
# The leaderboard table used to be a top-level ``models`` value. Since 17 October 2026 it
# is passed to the client component as ``initialModels``. Keep both shapes readable: saved
# fixtures and old pages use the first one, while the live page uses the second.
_BOARD_KEYS = ('"initialModels":[', '"models":[')
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


def _by_id(stream: str) -> dict[str, dict]:
    return {record["id"]: record for record in _records(stream).values()}


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
        "source_id": record.get("id"),
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
    # Two spellings of the same figures: until 14 November 2026 (and in the saved fixture) the
    # table used the "median…" names and a flat terminalBench40; since then outputSpeed,
    # timeToFirstAnswerToken and a "scores" map. Neither carries the other's.
    cost = _num(entry.get("intelligenceIndexCostPerTask"))
    terminal = _num(entry.get("terminalBench40"))
    if terminal is None:
        terminal = _num((entry.get("scores") or {}).get("terminalbench-4-0"))
    measured = {
        "source_name": entry["name"],
        "score": _round(_num(entry.get("intelligenceIndex"))),
        "cost_uusd": usd_to_uusd(cost),
        "terminal_bench": _round(terminal * 100) if terminal is not None else None,
        "tokens_per_second": _round(
            _num(entry.get("medianOutputTokensPerSecond")) or _num(entry.get("outputSpeed"))
        ),
        "first_answer_seconds": _round(
            _num(entry.get("medianTimeToFirstAnswerTokenSeconds"))
            or _num(entry.get("timeToFirstAnswerToken"))
            or None
        ),
        "thinking_seconds": _round(_num(entry.get("medianReasoningTimeSeconds")) or None),
        "end_to_end_seconds": _round(_num(entry.get("medianEndToEndResponseTimeSeconds")) or None),
        "deprecated": bool(entry.get("deprecated")),
    }
    # Only when the table has it: an older table without it must not erase the page's clock.
    task_seconds = _num(entry.get("intelligenceIndexTimePerTask"))
    if task_seconds:
        measured["task_seconds"] = _round(task_seconds)
    return measured


def parse_board(raw: str) -> list[dict]:
    """Every variant on the leaderboard, as the raw entries of its table."""
    stream = _payload(raw)
    board: list[dict] = []
    for marker in _BOARD_KEYS:
        start = stream.find(marker)
        if start < 0:
            continue
        try:
            # Decode from the opening bracket rather than the surrounding RSC props. Their
            # component tree may move again; the table itself is the contract we validate.
            table, _ = json.JSONDecoder().raw_decode(stream, start + len(marker) - 1)
            board = [
                entry
                for entry in table
                if isinstance(entry, dict)
                and (entry.get("slug") or entry.get("id"))
                and "intelligenceIndex" in entry
            ]
        except (json.JSONDecodeError, TypeError):
            board = []
        if board:
            break
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


def parse_release(raw: str) -> tuple[dict[str, dict], str]:
    """Every variant record on a release's page, by record id, and the index version it names."""
    version = _VERSION.search(raw)
    rows = {
        record_id: _row(record) for record_id, record in _by_id(_payload(raw)).items()
    }
    return rows, version.group(1) if version else ""


def off_board(rows: list[dict], sold: set[str], archived: list[dict]) -> dict[str, str]:
    """Models we can buy that the table dropped, and the page each was last read from.

    By the archived slugs: the shortest is the release's own page, and any variant URL
    redirects there anyway. A model never archived has no page we know of.
    """
    on_board = {row["model_key"] for row in rows}
    pages: dict[str, str] = {}
    for row in archived:
        key, slug = row["model_key"], row.get("source_slug")
        if key in sold and key not in on_board and slug:
            if key not in pages or len(slug) < len(pages[key]):
                pages[key] = slug
    return pages


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
            slug: {
                key: row.get(key)
                for key in ("model_key", "effort", "vendor", "released", "source_id")
            }
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
    # The archive's variants and fold losers by record id, for entries that carry no slug.
    slug_of = {row["source_id"]: row["source_slug"] for row in archived if row.get("source_id")}
    slug_of.update({info["source_id"]: slug for slug, info in folded.items() if info.get("source_id")})

    pages: dict[str, dict] = {}
    releases: dict[str, list[dict]] = {}
    for entry in board:
        if not entry.get("slug") and entry.get("id") in slug_of:
            entry["slug"] = slug_of[entry["id"]]
        if not entry.get("slug"):
            releases.setdefault((entry.get("release") or {}).get("slug") or "", []).append(entry)
            continue
        slug = entry["slug"]
        if not needs_page(entry, known.get(slug), slug in folded):
            continue
        if entry.get("release"):
            releases.setdefault(entry["release"].get("slug") or "", []).append(entry)
            continue
        page = await client.get(f"{SITE_URL}/{slug}", follow_redirects=True)
        page.raise_for_status()
        pages[slug], page_version = parse_variant(page.text, slug)
        # A new index version re-scores every variant, so the pages carry it in.
        version = page_version or version
        await asyncio.sleep(PAGE_PAUSE_S)

    for release, entries in releases.items():
        if not release:
            raise ValueError(f"artificialanalysis: {entries[0]['name']} has no slug and no release")
        page = await client.get(f"{SITE_URL}/{release}", follow_redirects=True)
        page.raise_for_status()
        rows, page_version = parse_release(page.text)
        version = page_version or version
        for entry in entries:
            row = rows.get(entry.get("id"))
            if row is None:
                raise ValueError(
                    f"artificialanalysis: no record for {entry['name']} on the {release} page"
                )
            entry["slug"] = row["source_slug"]
            pages[entry["slug"]] = row
        await asyncio.sleep(PAGE_PAUSE_S)
    rows, meta = merge(board, known, folded, pages, version)

    sold = {row["model_key"] for row in db.latest(settings.db_path, "copilot")[0]}
    extra: list[dict] = []
    for key, slug in sorted(off_board(rows, sold, archived).items()):
        page = await client.get(f"{SITE_URL}/{slug}", follow_redirects=True)
        if page.status_code == 404:
            continue  # the site retired it: it joins the models nobody scores
        page.raise_for_status()
        found, _ = parse_release(page.text)
        extra.extend(row for row in found.values() if row["model_key"] == key)
        await asyncio.sleep(PAGE_PAUSE_S)
    if extra:
        rows, losers = fold(rows + extra)
        meta["row_count"] = len(rows)
        meta["priced_count"] = sum(1 for row in rows if row["cost_uusd"] is not None)
        meta["off_board"] = sorted({row["model_key"] for row in extra})
        meta["folded"].update(
            {
                slug: {key: row.get(key) for key in ("model_key", "effort", "vendor", "released", "source_id")}
                for slug, row in losers.items()
            }
        )
    return rows, meta
