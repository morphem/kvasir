"""The polling loop.

One loop, waking every minute, asking each source "are you due?" — the due check reads the
last successful run out of the database, so a restart never loses the schedule and a
container that was down for a day catches up immediately instead of waiting a full
interval.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import db
from .collect import BACKFILL_SOURCE, LOCK, backfill_drift, client, collect_source
from .collectors import MODULES
from .config import settings

log = logging.getLogger("kvasir.scheduler")

TICK_SECONDS = 60


def interval_minutes(source: str) -> int:
    return {
        "stupidlevel": settings.interval_stupidlevel,
        "cursorbench": settings.interval_cursorbench,
        "copilot": settings.interval_copilot,
        BACKFILL_SOURCE: settings.interval_backfill,
    }.get(source, 720)


def due(source: str, status: dict) -> bool:
    entry = status.get(source) or {}
    last_run = entry.get("last_run")
    if not last_run:
        return True
    try:
        stamp = datetime.fromisoformat(last_run)
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamp >= timedelta(minutes=interval_minutes(source))


async def run_forever() -> None:
    while True:
        try:
            status = db.source_status(settings.db_path)
            pending = [source for source in MODULES if due(source, status)]
            # The run history is due on its own clock, tracked in the same run log, so a
            # restart neither loses nor repeats it.
            backfill_due = due(BACKFILL_SOURCE, status)
            if pending or backfill_due:
                async with LOCK, client() as http:
                    for source in pending:
                        await collect_source(source, http)
                    if backfill_due:
                        await backfill_drift(http)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must outlive any single failure
            log.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)
