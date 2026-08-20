"""The HTTP surface, served from an archive the test filled in."""

from conftest import fixture
from fastapi.testclient import TestClient

from kvasir import db
from kvasir.api import app
from kvasir.collectors import copilot, cursorbench, stupidlevel
from kvasir.config import settings


def seed():
    """Fill the archive the way a real collection round would — snapshot plus run log."""
    db.init(settings.db_path)
    for module, name in (
        (cursorbench, "cursorbench.html"),
        (copilot, "copilot-models-and-pricing.html"),
        (stupidlevel, "stupidlevel-scores.json"),
    ):
        rows, meta = module.parse(fixture(name))
        started = db.now_iso()
        snapshot_id, changed = db.archive(settings.db_path, module.SOURCE, rows, meta)
        db.log_run(
            settings.db_path, module.SOURCE, started, True, changed, len(rows), None, snapshot_id
        )


def client() -> TestClient:
    seed()
    return TestClient(app)


def test_health_reports_every_source():
    response = client().get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert set(body["sources"]) == {"cursorbench", "stupidlevel", "copilot"}


def test_view_is_one_consistent_payload():
    body = client().get("/api/view").json()
    assert body["ready"] is True
    assert body["benchmark_version"] == "3.2"
    assert set(body["verdicts"]) == {"architect", "worker", "scout"}
    assert body["tasks"] and body["ladder"] and body["drift"]
    assert body["archive"]["snapshots"] >= 3
    for source in body["sources"].values():
        assert source["url"].startswith("https://")
        assert source["interval_minutes"] > 0


def test_hidden_models_can_be_unhidden_on_demand():
    api = client()
    default_view = api.get("/api/view").json()
    everything = api.get("/api/view", params={"all": True}).json()
    assert len(everything["candidates"]) >= len(default_view["candidates"])
    assert everything["showing_all"] is True


def test_view_says_when_each_source_is_due_again():
    """The page counts down instead of offering a button that hits three foreign sites."""
    body = client().get("/api/view").json()
    for source in body["sources"].values():
        assert source["next_run"] > source["last_run"]


def test_manual_refresh_cannot_be_leaned_on():
    from kvasir import api

    api._last_manual_refresh = 0.0
    with TestClient(app) as api_client:
        first = api_client.post("/api/refresh", params={"source": "nope"})
        assert first.status_code == 404          # unknown source, no cooldown spent
        api._last_manual_refresh = __import__("time").monotonic()
        blocked = api_client.post("/api/refresh")
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["retry_after_s"] > 0


def test_the_page_itself_is_served():
    response = client().get("/")
    assert response.status_code == 200
    assert "Kvasir" in response.text


def test_the_run_history_job_has_its_own_clock_and_shows_its_age():
    """The sparklines froze once because this job ran daily while the score moved hourly."""
    from kvasir import scheduler
    from kvasir.collect import BACKFILL_SOURCE

    assert scheduler.interval_minutes(BACKFILL_SOURCE) == settings.interval_backfill
    assert settings.interval_backfill <= 12 * 60

    api = client()
    db.log_run(settings.db_path, BACKFILL_SOURCE, db.now_iso(), True, True, 22, None, None)
    body = api.get("/api/view").json()
    assert body["drift_history"]["last_run"]
    assert body["drift_history"]["interval_minutes"] == settings.interval_backfill


def test_a_backfill_that_is_overdue_is_scheduled_again():
    from kvasir import scheduler
    from kvasir.collect import BACKFILL_SOURCE

    stale = {"last_run": "2026-01-01T00:00:00+00:00"}
    assert scheduler.due(BACKFILL_SOURCE, {BACKFILL_SOURCE: stale}) is True
    assert scheduler.due(BACKFILL_SOURCE, {BACKFILL_SOURCE: {"last_run": db.now_iso()}}) is False
