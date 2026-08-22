"""Storage — an append-only archive of what each source said, and when.

The invariant this file exists to protect: **a number the page ever displayed can be
found again later.** The page is a weather report; the database is the climate record.

Shape:
  source_run   every poll attempt, successful or not — this is the honesty log
  snapshot     one archived reading per source, written only when the content changed
  observation  the rows of a snapshot, one per (model, effort)

Deduplication is by content hash, so polling AI Stupid Level hourly for a week does not
write 168 identical copies — it writes the handful of readings where something actually
moved, which is exactly the history worth charting.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  source       TEXT NOT NULL,
  captured_at  TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  meta_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS snapshot_source_time ON snapshot(source, captured_at DESC);

CREATE TABLE IF NOT EXISTS observation (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
  source      TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  model_key   TEXT NOT NULL,
  effort      TEXT NOT NULL DEFAULT 'default',
  score       REAL,
  cost_uusd   INTEGER,
  data_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observation_snapshot ON observation(snapshot_id);
CREATE INDEX IF NOT EXISTS observation_model ON observation(source, model_key, effort, captured_at);

CREATE TABLE IF NOT EXISTS source_run (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source      TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  ok          INTEGER NOT NULL DEFAULT 0,
  changed     INTEGER NOT NULL DEFAULT 0,
  row_count   INTEGER NOT NULL DEFAULT 0,
  error       TEXT,
  snapshot_id INTEGER REFERENCES snapshot(id)
);
CREATE INDEX IF NOT EXISTS source_run_time ON source_run(source, started_at DESC);

-- Drift as a time series, keyed by the *source's* timestamp so polling more often than
-- the source re-scores cannot inflate it. `series` keeps measurements apart:
--   aisl-run        individual benchmark runs, as published by AI Stupid Level
--   aisl-dashboard  the smoothed score the site shows, as archived by us
CREATE TABLE IF NOT EXISTS drift_history (
  model_key   TEXT NOT NULL,
  series      TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  score       REAL NOT NULL,
  PRIMARY KEY (model_key, series, captured_at)
) WITHOUT ROWID;

-- The page's own verdicts. A recommendation is a number the page displayed, so it belongs
-- in this archive like any other reading; deduplicated by content hash like the sources,
-- so a quiet week writes nothing and every row is a decision that actually moved.
CREATE TABLE IF NOT EXISTS recommendation (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at  TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS recommendation_time ON recommendation(captured_at DESC);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def payload_hash(rows: list[dict]) -> str:
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def archive(db_path: str, source: str, rows: list[dict], meta: dict) -> tuple[int | None, bool]:
    """Store a reading. Returns (snapshot_id, changed).

    An unchanged reading is not stored again — the previous snapshot still describes the
    present, and the run log records that we checked.
    """
    digest = payload_hash(rows)
    captured_at = now_iso()
    with connect(db_path) as conn:
        previous = conn.execute(
            "SELECT id, payload_hash, meta_json FROM snapshot WHERE source=? ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        if previous and previous["payload_hash"] == digest:
            # Same reading, so no new snapshot — but metadata we learned to extract since the
            # last write (a benchmark version, the AI-credit rate) must not be stuck in the
            # past just because the numbers held still.
            fresh_meta = json.dumps(meta, default=str)
            if fresh_meta != previous["meta_json"]:
                conn.execute(
                    "UPDATE snapshot SET meta_json=? WHERE id=?", (fresh_meta, previous["id"])
                )
            return previous["id"], False

        cursor = conn.execute(
            "INSERT INTO snapshot(source, captured_at, payload_hash, meta_json) VALUES (?,?,?,?)",
            (source, captured_at, digest, json.dumps(meta, default=str)),
        )
        snapshot_id = cursor.lastrowid
        conn.executemany(
            """INSERT INTO observation
               (snapshot_id, source, captured_at, model_key, effort, score, cost_uusd, data_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            [
                (
                    snapshot_id,
                    source,
                    captured_at,
                    row.get("model_key", ""),
                    row.get("effort", "default"),
                    row.get("score"),
                    row.get("cost_uusd"),
                    json.dumps(row, default=str),
                )
                for row in rows
            ],
        )
        return snapshot_id, True


def archive_recommendation(db_path: str, payload: dict) -> tuple[int | None, bool]:
    """Store the verdict. Only when the decision itself moved.

    Same contract as `archive`: an unchanged reading is not stored again, because the
    previous row still describes the present — this table is the answer to "what did the
    page recommend and when", not a diary of how often someone opened it.
    """
    digest = payload_hash([payload])
    with connect(db_path) as conn:
        previous = conn.execute(
            "SELECT id, payload_hash FROM recommendation ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if previous and previous["payload_hash"] == digest:
            return previous["id"], False
        cursor = conn.execute(
            "INSERT INTO recommendation(captured_at, payload_hash, payload_json) VALUES (?,?,?)",
            (now_iso(), digest, json.dumps(payload, default=str)),
        )
        return cursor.lastrowid, True


def recommendation_history(db_path: str, days: int = 365) -> list[dict]:
    """Every distinct verdict of the window, oldest first.

    Ordered by id, not by timestamp: two decisions inside one second share a
    `captured_at`, and the insertion order is the true chronology.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT captured_at, payload_json FROM recommendation
               WHERE captured_at>=? ORDER BY id""",
            (since,),
        ).fetchall()
    return [{"captured_at": row["captured_at"], **json.loads(row["payload_json"])} for row in rows]


def log_run(
    db_path: str,
    source: str,
    started_at: str,
    ok: bool,
    changed: bool,
    row_count: int,
    error: str | None,
    snapshot_id: int | None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO source_run
               (source, started_at, finished_at, ok, changed, row_count, error, snapshot_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (source, started_at, now_iso(), int(ok), int(changed), row_count, error, snapshot_id),
        )


def latest(db_path: str, source: str) -> tuple[list[dict], dict]:
    """Rows of the newest archived snapshot for a source, plus its metadata."""
    with connect(db_path) as conn:
        snapshot = conn.execute(
            "SELECT * FROM snapshot WHERE source=? ORDER BY id DESC LIMIT 1", (source,)
        ).fetchone()
        if not snapshot:
            return [], {}
        rows = conn.execute(
            "SELECT data_json FROM observation WHERE snapshot_id=? ORDER BY id", (snapshot["id"],)
        ).fetchall()
        meta = json.loads(snapshot["meta_json"])
        meta.update(
            {
                "captured_at": snapshot["captured_at"],
                "snapshot_id": snapshot["id"],
                "payload_hash": snapshot["payload_hash"][:12],
            }
        )
        return [json.loads(row["data_json"]) for row in rows], meta


def history(
    db_path: str, source: str, model_key: str, effort: str | None = None, days: int = 30
) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    query = """SELECT captured_at, score, cost_uusd FROM observation
               WHERE source=? AND model_key=? AND captured_at>=?"""
    params: list = [source, model_key, since]
    if effort:
        query += " AND effort=?"
        params.append(effort)
    query += " ORDER BY captured_at"
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def store_drift_points(db_path: str, model_key: str, series: str, points: list[dict]) -> int:
    """Idempotent insert — re-running a backfill costs nothing and changes nothing."""
    if not points:
        return 0
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            """INSERT OR IGNORE INTO drift_history(model_key, series, captured_at, score)
               VALUES (?,?,?,?)""",
            [(model_key, series, point["captured_at"], float(point["score"])) for point in points],
        )
        return conn.total_changes - before


def drift_series(db_path: str, model_key: str, series: str = "aisl-run", days: int = 14) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT captured_at, score FROM drift_history
               WHERE model_key=? AND series=? AND captured_at>=? ORDER BY captured_at""",
            (model_key, series, since),
        ).fetchall()
    return [dict(row) for row in rows]


def drift_summary(db_path: str, days: int = 7) -> dict[str, dict]:
    """How far a model moved across the window — the "80 yesterday, 67 today" number.

    Individual benchmark runs swing wildly (a model sitting at 73 produces single runs from
    62 to 91), so comparing the literal first and last point measures noise, not drift.
    The delta compares the mean of the first fifth of the window against the mean of the
    last fifth, which is small enough to stay responsive and wide enough to stop one bad
    run from inventing a trend.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    series: dict[str, list[float]] = {}
    stamps: dict[str, tuple[str, str]] = {}
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT model_key, captured_at, score FROM drift_history
               WHERE series='aisl-run' AND captured_at>=? ORDER BY model_key, captured_at""",
            (since,),
        ).fetchall()
    for row in rows:
        series.setdefault(row["model_key"], []).append(row["score"])
        first_at = stamps.get(row["model_key"], (row["captured_at"], row["captured_at"]))[0]
        stamps[row["model_key"]] = (first_at, row["captured_at"])

    out: dict[str, dict] = {}
    for model_key, scores in series.items():
        window = max(1, len(scores) // 5)
        head = sum(scores[:window]) / window
        tail = sum(scores[-window:]) / window
        out[model_key] = {
            "first": scores[0],
            "last": scores[-1],
            "first_at": stamps[model_key][0],
            "last_at": stamps[model_key][1],
            "points": len(scores),
            "min": min(scores),
            "max": max(scores),
            "delta": round(tail - head, 1),
        }
    return out


def source_status(db_path: str) -> dict[str, dict]:
    """What the UI shows in the freshness strip: last check, last change, last error."""
    out: dict[str, dict] = {}
    with connect(db_path) as conn:
        for row in conn.execute(
            """SELECT source,
                      MAX(started_at) AS last_run,
                      SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS failures,
                      COUNT(*) AS runs
               FROM source_run GROUP BY source"""
        ):
            out[row["source"]] = {
                "last_run": row["last_run"],
                "runs": row["runs"],
                "failures": row["failures"],
            }
        for row in conn.execute(
            """SELECT source, COUNT(*) AS snapshots, MIN(captured_at) AS first_seen,
                      MAX(captured_at) AS last_change
               FROM snapshot GROUP BY source"""
        ):
            entry = out.setdefault(row["source"], {})
            entry.update(
                {
                    "snapshots": row["snapshots"],
                    "first_seen": row["first_seen"],
                    "last_change": row["last_change"],
                }
            )
        for row in conn.execute(
            """SELECT source, error, started_at FROM source_run
               WHERE ok=0 AND id IN (SELECT MAX(id) FROM source_run WHERE ok=0 GROUP BY source)"""
        ):
            entry = out.setdefault(row["source"], {})
            entry["last_error"] = row["error"]
            entry["last_error_at"] = row["started_at"]
    return out


def archive_stats(db_path: str) -> dict:
    with connect(db_path) as conn:
        snapshots = conn.execute("SELECT COUNT(*) AS n FROM snapshot").fetchone()["n"]
        observations = conn.execute("SELECT COUNT(*) AS n FROM observation").fetchone()["n"]
        recommendations = conn.execute(
            "SELECT COUNT(*) AS n FROM recommendation"
        ).fetchone()["n"]
        first = conn.execute("SELECT MIN(captured_at) AS t FROM snapshot").fetchone()["t"]
    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    return {
        "snapshots": snapshots,
        "observations": observations,
        "recommendations": recommendations,
        "since": first,
        "db_bytes": size,
    }
