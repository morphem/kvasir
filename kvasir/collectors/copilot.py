"""GitHub Copilot — which models we can actually pick at work, and what they bill.

Copilot charges AI credits per token, so this source answers "is this model available to
us, and what does a million tokens cost" — the availability filter and the price tag on
every verdict. It does not say anything about quality; that is what the other two are for.

The page is real <table> markup, one table per vendor, with headers that differ slightly
between vendors (some carry Tier/Threshold, some carry Cache write). We read by header
name rather than by column index so a new column does not shift every price by one.
"""

from __future__ import annotations

import re

from ..htmlparse import tables, text_lines, usd_to_uusd
from ..naming import model_key, split_effort, vendor_of

SOURCE = "copilot"
URL = "https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing"
LABEL = "GitHub Copilot"

# "the total is converted into AI credits, where 1 AI credit = $0.01 USD" — the sentence that
# turns every price on this page into a credit budget. Read from the page rather than hardcoded,
# because the whole tier layer is built on it.
_CREDIT_RATE = re.compile(r"1 AI credit\s*=\s*\$(?P<usd>\d+(?:\.\d+)?)\s*USD", re.I)

_PRICE_COLUMNS = {
    "input": "input_uusd",
    "cached input": "cached_input_uusd",
    "cache write": "cache_write_uusd",
    "output": "output_uusd",
}
MIN_ROWS = 5


def _header_index(header: list[str]) -> dict[str, int]:
    return {cell.strip().lower(): i for i, cell in enumerate(header)}


def parse(raw: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    for table in tables(raw):
        if not table:
            continue
        header = table[0]
        index = _header_index(header)
        if "model" not in index or "input" not in index:
            continue

        for cells in table[1:]:
            # Footnote markers render as an extra one-character cell after the model.
            if len(cells) == len(header) + 1 and len(cells[1]) <= 2 and cells[1].isdigit():
                cells = [cells[0]] + cells[2:]
            if len(cells) < len(header):
                continue

            name = cells[index["model"]]
            base, effort = split_effort(name)
            key = model_key(base)
            row = {
                "model_key": key,
                "effort": effort,
                "vendor": vendor_of(key),
                "source_name": name,
                "release_status": cells[index["release status"]] if "release status" in index else "",
                "category": cells[index["category"]] if "category" in index else "",
                "tier": cells[index["tier"]] if "tier" in index else "Default",
                "threshold": cells[index["threshold (input tokens)"]]
                if "threshold (input tokens)" in index
                else "",
            }
            for column, field in _PRICE_COLUMNS.items():
                row[field] = usd_to_uusd(cells[index[column]]) if column in index else None
            if row["input_uusd"] is None and row["output_uusd"] is None:
                continue
            rows.append(row)

    if len(rows) < MIN_ROWS:
        raise ValueError(f"copilot: parsed only {len(rows)} rows — page shape changed")

    # Long-context variants repeat the model; the default tier is the one we price against.
    default_tier = [r for r in rows if r["tier"].lower().startswith("default") or not r["tier"]]
    meta = {"row_count": len(rows), "default_tier_rows": len(default_tier)}

    for line in text_lines(raw):
        found = _CREDIT_RATE.search(line)
        if found:
            meta["credit_usd"] = float(found["usd"])
            meta["credit_usd_quote"] = line[:400]
            break

    return rows, meta


async def fetch(client) -> tuple[list[dict], dict]:
    response = await client.get(URL, follow_redirects=True)
    response.raise_for_status()
    return parse(response.text)
