"""The archive: what it keeps, what it refuses to keep twice."""

import os
import tempfile

from kvasir import db


def fresh_db() -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="kvasir-db-"), "kvasir.db")
    db.init(path)
    return path


ROWS = [
    {"model_key": "opus-5", "effort": "max", "score": 70.0, "cost_uusd": 8_230_000},
    {"model_key": "sonnet-5", "effort": "high", "score": 56.9, "cost_uusd": 2_130_000},
]


def test_identical_readings_are_stored_once():
    path = fresh_db()
    first, changed_first = db.archive(path, "cursorbench", ROWS, {"benchmark_version": "3.2"})
    second, changed_second = db.archive(path, "cursorbench", ROWS, {"benchmark_version": "3.2"})
    assert changed_first is True and changed_second is False
    assert first == second
    assert db.archive_stats(path)["snapshots"] == 1


def test_a_changed_reading_becomes_a_new_snapshot():
    path = fresh_db()
    db.archive(path, "cursorbench", ROWS, {})
    moved = [dict(ROWS[0], score=69.1), ROWS[1]]
    _, changed = db.archive(path, "cursorbench", moved, {})
    assert changed is True
    assert db.archive_stats(path)["snapshots"] == 2
    rows, meta = db.latest(path, "cursorbench")
    assert rows[0]["score"] == 69.1
    assert meta["captured_at"]


def test_history_returns_the_series_for_one_model():
    path = fresh_db()
    db.archive(path, "cursorbench", ROWS, {})
    db.archive(path, "cursorbench", [dict(ROWS[0], score=68.0), ROWS[1]], {})
    points = db.history(path, "cursorbench", "opus-5", "max", days=1)
    assert [point["score"] for point in points] == [70.0, 68.0]


def test_drift_points_are_idempotent_and_summarised():
    path = fresh_db()
    points = [
        {"captured_at": "2026-08-12T10:00:00Z", "score": 80},
        {"captured_at": "2026-08-13T10:00:00Z", "score": 74},
        {"captured_at": "2026-08-14T10:00:00Z", "score": 67},
    ]
    assert db.store_drift_points(path, "opus-4.6", "aisl-run", points) == 3
    assert db.store_drift_points(path, "opus-4.6", "aisl-run", points) == 0
    summary = db.drift_summary(path, days=3650)["opus-4.6"]
    assert summary["delta"] == -13
    assert summary["min"] == 67 and summary["max"] == 80


def test_a_failed_run_is_recorded_and_visible():
    path = fresh_db()
    db.log_run(path, "cursorbench", db.now_iso(), False, False, 0, "HTTPError: 503", None)
    status = db.source_status(path)["cursorbench"]
    assert status["failures"] == 1
    assert status["last_error"].startswith("HTTPError")


def test_drift_delta_ignores_a_single_loud_run():
    """One good run at the end must not erase a week of decline."""
    path = fresh_db()
    high = [{"captured_at": f"2026-08-1{d}T{h:02d}:00:00Z", "score": 80}
            for d in (1, 2) for h in range(5)]
    low = [{"captured_at": f"2026-08-1{d}T{h:02d}:00:00Z", "score": 60}
           for d in (3, 4) for h in range(5)]
    low[-1]["score"] = 90  # the loud one
    db.store_drift_points(path, "sonnet-4.5", "aisl-run", high + low)
    summary = db.drift_summary(path, days=3650)["sonnet-4.5"]
    assert summary["points"] == 20
    assert summary["last"] == 90        # the raw series keeps it
    assert summary["delta"] < -10       # the verdict does not fall for it


def test_unchanged_rows_still_refresh_metadata():
    """A parser that learns a new fact must be able to store it without a data change."""
    path = fresh_db()
    db.archive(path, "copilot", ROWS, {"row_count": 2})
    snapshot_id, changed = db.archive(path, "copilot", ROWS, {"row_count": 2, "credit_usd": 0.01})
    assert changed is False
    assert db.archive_stats(path)["snapshots"] == 1
    _, meta = db.latest(path, "copilot")
    assert meta["credit_usd"] == 0.01


DECISION = {
    "verdicts": {"worker": {"pick": {"key": "sonnet-5", "effort": "high"}, "replaced": None}},
    "plans": {},
    "credit_usd": 0.01,
    "thresholds": {"worker_max_cost_usd": 2.5},
}


def test_the_verdict_is_archived_once_per_change():
    path = fresh_db()
    moved = {"verdicts": {"worker": {"pick": {"key": "opus-5", "effort": "max"}, "replaced": None}},
             "plans": {}, "credit_usd": 0.01, "thresholds": DECISION["thresholds"]}
    first, changed_a = db.archive_recommendation(path, DECISION)
    again, changed_b = db.archive_recommendation(path, dict(DECISION))
    _, changed_c = db.archive_recommendation(path, moved)
    assert (changed_a, changed_b, changed_c) == (True, False, True)
    assert first == again  # the unchanged reading points at the same row
    history = db.recommendation_history(path, days=1)
    assert [point["verdicts"]["worker"]["pick"]["key"] for point in history] == [
        "sonnet-5",
        "opus-5",
    ]


def test_recommendations_are_counted_in_the_archive_stats():
    path = fresh_db()
    db.archive_recommendation(path, DECISION)
    stats = db.archive_stats(path)
    assert stats["recommendations"] == 1
