"""HTTP surface: one JSON payload for the page, plus the archive underneath it.

The page is a single fetch of /api/view. Everything the UI renders — verdicts, ladder,
drift, prices, freshness — comes from that one response, so what you see is always one
consistent reading rather than four endpoints disagreeing about the time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import db, recommend, scheduler
from .collect import BACKFILL_SOURCE, DASHBOARD_SERIES, DRIFT_SERIES, collect_all
from .collectors import MODULES, SOURCE_LABELS
from .config import settings
from .naming import display_name

__version__ = "1.0.0"

log = logging.getLogger("kvasir")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# In the container the package is installed into site-packages while the page stays at
# /app/web, so the location is explicit there and inferred from the repo layout locally.
# Manual collection is a courtesy to the owner, not a button on a shared page: three third
# party sites are on the other end of it. The page shows a countdown instead and this endpoint
# refuses to be leaned on.
MANUAL_REFRESH_COOLDOWN_S = 300
_last_manual_refresh = 0.0

WEB_DIR = os.environ.get("KVASIR_WEB_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init(settings.db_path)
    log.info("kvasir %s — data dir %s", __version__, settings.data_dir)

    async def bootstrap():
        # Anything the archive is missing is fetched immediately; the scheduler then keeps
        # it fresh. A cold container is useful within seconds, not at the next interval.
        missing = [s for s in MODULES if not db.latest(settings.db_path, s)[0]]
        if missing:
            await collect_all(missing)

    app.state.tasks = (
        [asyncio.create_task(bootstrap()), asyncio.create_task(scheduler.run_forever())]
        if settings.autostart
        else []
    )
    try:
        yield
    finally:
        for task in app.state.tasks:
            task.cancel()


app = FastAPI(title="Kvasir", version=__version__, lifespan=lifespan)


def _next_run(last_run: str | None, interval_minutes: int) -> str | None:
    """When this source is due again — the page counts down to it."""
    if not last_run:
        return None
    try:
        stamp = datetime.fromisoformat(last_run)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (stamp + timedelta(minutes=interval_minutes)).isoformat(timespec="seconds")


def _sources_block() -> dict:
    status = db.source_status(settings.db_path)
    out = {}
    for source, module in MODULES.items():
        _, meta = db.latest(settings.db_path, source)
        entry = status.get(source, {})
        interval = scheduler.interval_minutes(source)
        out[source] = {
            "label": SOURCE_LABELS.get(source, source),
            "url": getattr(module, "SITE_URL", module.URL),
            "api_url": module.URL,
            "interval_minutes": interval,
            "captured_at": meta.get("captured_at"),
            "last_run": entry.get("last_run"),
            "next_run": _next_run(entry.get("last_run"), interval),
            "last_change": entry.get("last_change"),
            "snapshots": entry.get("snapshots", 0),
            "runs": entry.get("runs", 0),
            "failures": entry.get("failures", 0),
            "last_error": entry.get("last_error"),
            "meta": {k: v for k, v in meta.items() if k not in {"payload_hash", "snapshot_id"}},
        }
    return out


def _drift_block(ai_rows: list[dict]) -> list[dict]:
    """AI Stupid Level, enriched with what our own archive has seen move."""
    summary = db.drift_summary(settings.db_path, days=7)
    out = []
    for row in sorted(ai_rows, key=lambda r: -(r.get("score") or 0)):
        key = row["model_key"]
        moved = summary.get(key, {})
        series = db.drift_series(settings.db_path, key, DRIFT_SERIES, days=7)
        out.append(
            {
                "key": key,
                "label": display_name(key),
                "vendor": row.get("vendor"),
                "score": row.get("score"),
                "trend": row.get("trend"),
                "status": row.get("status"),
                "stale": row.get("is_stale"),
                "stale_hours": row.get("stale_hours"),
                "ci_low": row.get("ci_low"),
                "ci_high": row.get("ci_high"),
                "uses_reasoning_effort": row.get("uses_reasoning_effort"),
                "delta_7d": moved.get("delta"),
                "min_7d": moved.get("min"),
                "max_7d": moved.get("max"),
                "points": [[p["captured_at"], p["score"]] for p in series],
            }
        )
    return out


@app.get("/api/health")
def health():
    status = db.source_status(settings.db_path)
    healthy = all(
        (status.get(source, {}).get("snapshots") or 0) > 0 for source in MODULES
    )
    return {"ok": healthy, "version": __version__, "sources": {s: status.get(s, {}) for s in MODULES}}


@app.get("/api/view")
def view(all: bool = Query(False, description="include models hidden by configuration")):
    cb_rows, cb_meta = db.latest(settings.db_path, "cursorbench")
    ai_rows, _ = db.latest(settings.db_path, "stupidlevel")
    cp_rows, cp_meta = db.latest(settings.db_path, "copilot")
    hidden = [] if all else settings.hidden_models
    payload = recommend.build(
        cb_rows, ai_rows, cp_rows, settings, hidden, credit_usd=cp_meta.get("credit_usd")
    )
    payload["credit_usd_quote"] = cp_meta.get("credit_usd_quote")
    payload["hidden_by_config"] = settings.hidden_models
    payload["showing_all"] = all
    payload.update(
        {
            "version": __version__,
            "generated_at": db.now_iso(),
            "benchmark_version": cb_meta.get("benchmark_version"),
            "sources": _sources_block(),
            "drift": _drift_block(ai_rows),
            "archive": db.archive_stats(settings.db_path),
            "drift_history": {
                **(db.source_status(settings.db_path).get(BACKFILL_SOURCE) or {}),
                "interval_minutes": scheduler.interval_minutes(BACKFILL_SOURCE),
            },
            "ready": bool(cb_rows and ai_rows and cp_rows),
        }
    )
    return payload


@app.get("/api/drift/{model_key}")
def drift(model_key: str, days: int = Query(14, ge=1, le=365), series: str = DRIFT_SERIES):
    if series not in (DRIFT_SERIES, DASHBOARD_SERIES):
        raise HTTPException(400, "unknown series")
    return {
        "model_key": model_key,
        "series": series,
        "points": db.drift_series(settings.db_path, model_key, series, days),
    }


@app.get("/api/recommendations")
def recommendations(days: int = Query(365, ge=1, le=3650)):
    """Every distinct verdict the page has shown in the window — its own change log."""
    return {"days": days, "points": db.recommendation_history(settings.db_path, days)}


@app.get("/api/history")
def history(
    source: str,
    model: str,
    effort: str | None = None,
    days: int = Query(90, ge=1, le=3650),
):
    if source not in MODULES:
        raise HTTPException(404, "unknown source")
    return {
        "source": source,
        "model_key": model,
        "effort": effort,
        "points": db.history(settings.db_path, source, model, effort, days),
    }


@app.post("/api/refresh")
async def refresh(source: str | None = None):
    """Collect now. Rate limited, and it never triggers the history backfill.

    The scheduler already keeps everything current; this exists for the moment after a
    deploy when waiting an hour to see the page populated is silly.
    """
    global _last_manual_refresh
    if source and source not in MODULES:
        raise HTTPException(404, "unknown source")
    waited = time.monotonic() - _last_manual_refresh
    if waited < MANUAL_REFRESH_COOLDOWN_S:
        raise HTTPException(
            429,
            detail={
                "error": "collection was run recently",
                "retry_after_s": int(MANUAL_REFRESH_COOLDOWN_S - waited),
            },
        )
    _last_manual_refresh = time.monotonic()
    return {"results": await collect_all([source] if source else None)}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
