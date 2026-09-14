"""Artificial Analysis — how fast a model actually answers.

The fourth source, and the only one that measures time. CursorBench prices a task and
counts its steps; AI Stupid Level scores quality; neither publishes a second of wall clock.
That gap showed on the page as a verdict nobody followed: a model can win on score and cost
and still be the wrong one to start, because you sit watching it think.

Artificial Analysis runs models on dedicated hardware and publishes output speed in tokens
per second. The page carries its charts as schema.org Dataset blocks — proper JSON-LD, one
block per metric, each row labelled with the model and the effort it ran at — so this is the
one source that needs no scraping heuristics at all.

Coverage is partial and that matters: some models on our board have no measurement here.
A missing number is not a slow model, and the rules downstream treat it that way.
"""

from __future__ import annotations

import html
import json
import os
import re

from ..naming import model_key, split_effort, vendor_of

SOURCE = "speed"
# A model page, not the listing. Both carry schema.org Dataset blocks, but the model pages
# add the ones that matter here — latency and end-to-end response time — and their rows are
# per effort rather than one figure per model. The datasets are global leaderboards: two
# different model pages return byte-identical sets, so this URL is an entry point, not a
# subject. It is an environment variable because the page it names could be retired.
URL = os.environ.get(
    "KVASIR_SPEED_URL", "https://artificialanalysis.ai/models/claude-opus-5"
)
SITE_URL = "https://artificialanalysis.ai/"
LABEL = "Artificial Analysis"

MIN_ROWS = 5

_LD_BLOCK = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
# "Claude Opus 5 (max)" / "Gemini 3.8 Flash (high)" / "Claude Fable 5.1 (max with fallback)"
_QUALIFIER = re.compile(r"\s*\(([^)]+)\)\s*$")

# Units are quoted from the dataset descriptions on the page, not assumed:
#   Speed / Output Speed          "Output tokens per second"
#   Latency: Time To First Answer Token
#                                 "Seconds to first answer token received · Accounts for
#                                  reasoning model 'thinking' time"
#   End-to-End Response Time      "Seconds to output 500 tokens, including reasoning model
#                                  'thinking' time"
# The latency charts are stacked bars, so the components have to be added up rather than read
# off one key.
SPEED_KEYS = ("outputSpeed", "medianOutputSpeed")


def _label_parts(label: str) -> tuple[str, str]:
    """Split "Claude Opus 5 (max)" into a model key and an effort.

    The qualifier is not always an effort — "(with fallback)", "(Non-reasoning)" — so only
    the words our own ladder recognises are read as one, and the rest is dropped rather than
    guessed at.
    """
    found = _QUALIFIER.search(label)
    name = label[: found.start()] if found else label
    effort = "default"
    if found:
        # "max with fallback" -> "max"
        head = found.group(1).split(" with ")[0].strip()
        _, parsed = split_effort(f"model {head}")
        effort = parsed
    return model_key(name.strip()), effort


def parse(raw: str) -> tuple[list[dict], dict]:
    merged: dict[str, dict] = {}
    datasets: list[str] = []

    for block in _LD_BLOCK.findall(raw):
        try:
            document = json.loads(html.unescape(block))
        except json.JSONDecodeError:
            continue
        if not isinstance(document, dict) or document.get("@type") != "Dataset":
            continue
        rows = document.get("data")
        if not isinstance(rows, list):
            continue
        datasets.append(str(document.get("name", "")))
        for row in rows:
            if not isinstance(row, dict) or "label" not in row:
                continue
            entry = merged.setdefault(row["label"], {})
            for key, value in row.items():
                if key in ("label", "detailsUrl") or not isinstance(value, (int, float)):
                    continue
                entry[key] = float(value)

    rows = []
    for label, metrics in merged.items():
        speed = next((metrics[k] for k in SPEED_KEYS if metrics.get(k)), None)
        # A stacked bar with no data reads as zero, and a zero-second wait would make the
        # slowest model look like the fastest. Absent is absent.
        input_time = metrics.get("inputTime") or None
        thinking = metrics.get("reasoningTime") or None
        answering = metrics.get("answerTime") or None
        first_token = (input_time or 0) + (thinking or 0) if input_time or thinking else None
        end_to_end = (
            (input_time or 0) + (thinking or 0) + (answering or 0) if answering else None
        )
        if speed is None and first_token is None and end_to_end is None:
            continue  # this source is here for the clock; a row without one carries nothing

        key, effort = _label_parts(label)
        rows.append(
            {
                "model_key": key,
                "effort": effort,
                "vendor": vendor_of(key),
                "source_name": label,
                "tokens_per_second": round(speed, 1) if speed else None,
                "first_answer_seconds": round(first_token, 1) if first_token else None,
                "thinking_seconds": round(thinking, 1) if thinking else None,
                "end_to_end_seconds": round(end_to_end, 1) if end_to_end else None,
                "decode_minutes_per_task": metrics.get("timePerTask") or None,
                "metrics": {k: round(v, 3) for k, v in metrics.items()},
            }
        )

    if len(rows) < MIN_ROWS:
        raise ValueError(f"speed: parsed only {len(rows)} measured models — page shape changed")

    return rows, {"row_count": len(rows), "datasets": sorted(set(datasets))[:12]}


async def fetch(client) -> tuple[list[dict], dict]:
    response = await client.get(URL, follow_redirects=True)
    response.raise_for_status()
    return parse(response.text)
