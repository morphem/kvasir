"""Collection: fetch a source, archive it, and write down what happened.

Every poll produces a source_run row whether it worked or not. A source that has been
failing for two days must be visible on the page — a stale number presented as current is
the one failure mode this project cannot have.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from . import db
from .collectors import MODULES
from .config import settings

log = logging.getLogger("kvasir.collect")

# Boot-time catch-up and the scheduler tick can land at the same moment; without this they
# would both walk the whole model list against someone else's API.
LOCK = asyncio.Lock()

DRIFT_SERIES = "aisl-run"
DASHBOARD_SERIES = "aisl-dashboard"


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.request_timeout_s,
        headers={"User-Agent": settings.user_agent, "Accept-Language": "en"},
        follow_redirects=True,
    )


async def collect_source(source: str, http: httpx.AsyncClient) -> dict:
    module = MODULES[source]
    started = db.now_iso()
    try:
        rows, meta = await module.fetch(http)
        snapshot_id, changed = db.archive(settings.db_path, source, rows, meta)
        db.log_run(settings.db_path, source, started, True, changed, len(rows), None, snapshot_id)
        if source == "stupidlevel":
            _store_dashboard_points(rows)
        log.info("collected %s: %d rows, changed=%s", source, len(rows), changed)
        return {"source": source, "ok": True, "rows": len(rows), "changed": changed}
    except Exception as exc:  # noqa: BLE001 - any failure is a data point, not a crash
        message = f"{type(exc).__name__}: {exc}"[:500]
        db.log_run(settings.db_path, source, started, False, False, 0, message, None)
        log.warning("collect %s failed: %s", source, message)
        return {"source": source, "ok": False, "error": message}


def _store_dashboard_points(rows: list[dict]) -> None:
    """Archive the headline drift score against the source's own timestamp."""
    for row in rows:
        if row.get("score") is None or not row.get("last_updated"):
            continue
        db.store_drift_points(
            settings.db_path,
            row["model_key"],
            DASHBOARD_SERIES,
            [{"captured_at": row["last_updated"], "score": row["score"]}],
        )


async def backfill_drift(http: httpx.AsyncClient, period: str = "7d") -> dict:
    """Pull the published run history for every model we track.

    Idempotent, so it can run on every boot: the primary key drops the points we already
    have and keeps whatever is new.
    """
    from .collectors import stupidlevel

    rows, _ = db.latest(settings.db_path, "stupidlevel")
    added = 0
    models = 0
    for row in rows:
        model_id = row.get("source_id")
        if not model_id:
            continue
        try:
            points = await stupidlevel.fetch_history(http, model_id, period)
        except Exception as exc:  # noqa: BLE001
            log.warning("drift backfill for %s failed: %s", row.get("model_key"), exc)
            continue
        added += db.store_drift_points(settings.db_path, row["model_key"], DRIFT_SERIES, points)
        models += 1
        await asyncio.sleep(0.2)  # be a polite guest on someone else's API
    log.info("drift backfill: %d models, %d new points", models, added)
    return {"models": models, "points_added": added}


async def collect_all(sources: list[str] | None = None, with_backfill: bool = False) -> list[dict]:
    async with LOCK, client() as http:
        results = []
        for source in sources or list(MODULES):
            results.append(await collect_source(source, http))
        if with_backfill and any(r["source"] == "stupidlevel" and r["ok"] for r in results):
            await backfill_drift(http)
        return results
