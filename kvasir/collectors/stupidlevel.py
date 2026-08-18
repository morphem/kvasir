"""AI Stupid Level — the drift signal: is the model I trusted last week still that model.

This is the fast-moving source. It re-benchmarks continuously and publishes a 0-100 score
per model with a trend and a confidence interval, which is the only way to catch a model
quietly getting worse under a name that did not change.

It is a JSON API (the site is open source), so there is nothing to scrape. Effort is not
published per score — the models flagged `usesReasoningEffort` are run at the provider
default — and the UI says so rather than implying these numbers are comparable to
CursorBench's per-effort rows.
"""

from __future__ import annotations

from ..naming import model_key, split_effort, vendor_of

SOURCE = "stupidlevel"
URL = "https://aistupidlevel.info/api/dashboard/scores"
SITE_URL = "https://aistupidlevel.info/"
LABEL = "AI Stupid Level"

MIN_ROWS = 3


def parse(raw: str | dict) -> tuple[list[dict], dict]:
    import json

    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not payload.get("success"):
        raise ValueError("stupidlevel: API reported failure")

    rows = []
    for item in payload.get("data", []):
        base, effort = split_effort(item.get("name", ""))
        key = model_key(base)
        rows.append(
            {
                "model_key": key,
                "effort": effort,
                "vendor": vendor_of(key),
                "source_id": str(item.get("id", "")),
                "source_name": item.get("name", ""),
                "provider": item.get("provider", ""),
                "score": _num(item.get("currentScore")),
                "trend": item.get("trend", ""),
                "status": item.get("status", ""),
                "is_stale": bool(item.get("isStale")),
                "stale_hours": _num(item.get("staleDuration")),
                "ci_low": _num(item.get("confidenceLower")),
                "ci_high": _num(item.get("confidenceUpper")),
                "std_error": _num(item.get("standardError")),
                "uses_reasoning_effort": bool(item.get("usesReasoningEffort")),
                "last_updated": item.get("lastUpdated", ""),
            }
        )

    if len(rows) < MIN_ROWS:
        raise ValueError(f"stupidlevel: only {len(rows)} models returned")

    return rows, {
        "period": payload.get("period", ""),
        "sort_by": payload.get("sortBy", ""),
        "row_count": len(rows),
    }


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def fetch(client) -> tuple[list[dict], dict]:
    response = await client.get(URL)
    response.raise_for_status()
    return parse(response.text)


HISTORY_URL = "https://aistupidlevel.info/api/dashboard/history/{model_id}?period={period}"


async def fetch_history(client, model_id: str, period: str = "7d") -> list[dict]:
    """The source's own per-run scores for one model.

    Kvasir archives the dashboard score itself, but that series only starts the day this
    container did. Pulling the published run history gives the drift chart a real week of
    data on the first boot. The two are kept apart in storage and labelled apart in the UI
    because they are not the same measurement: these are individual benchmark runs, the
    dashboard score is their smoothed conversion.
    """
    response = await client.get(HISTORY_URL.format(model_id=model_id, period=period))
    response.raise_for_status()
    payload = response.json()
    points = []
    for item in payload.get("data", []):
        score = item.get("score")
        stamp = item.get("timestamp")
        if score is None or not stamp:
            continue
        points.append({"captured_at": stamp, "score": float(score)})
    return points
