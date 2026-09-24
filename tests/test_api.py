"""The HTTP surface, served from an archive the test filled in."""

from conftest import fixture
from fastapi.testclient import TestClient

from kvasir import db
from kvasir.api import app
from kvasir.collectors import artificialanalysis, copilot, stupidlevel
from kvasir.config import settings


def seed():
    """Fill the archive the way a real collection round would — snapshot plus run log."""
    db.init(settings.db_path)
    for module, name in (
        (artificialanalysis, "artificialanalysis-model-page.html"),
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
    assert set(body["sources"]) == {"artificialanalysis", "stupidlevel", "copilot"}


def test_view_is_one_consistent_payload():
    body = client().get("/api/view").json()
    assert body["ready"] is True
    assert body["benchmark_version"] == "4.3"
    assert set(body["plans"]) == {"basic", "heavy", "power"}
    assert body["default_patience"] in {p["id"] for p in body["patience"]}
    assert body["tasks"] and body["ladder"] and body["drift"]
    assert body["archive"]["snapshots"] >= 3
    for source in body["sources"].values():
        assert source["url"].startswith("https://")
        assert source["interval_minutes"] > 0
        assert source["failing"] is False  # the page reads health from the payload, not a guess


def test_unavailable_models_can_be_shown_on_demand():
    api = client()
    default_view = api.get("/api/view").json()
    everything = api.get("/api/view", params={"all": True}).json()
    assert len(everything["candidates"]) > len(default_view["candidates"])
    assert everything["showing_all"] is True
    assert everything["excluded"] == []


def test_the_default_board_only_holds_models_we_can_start():
    """The verdict must never name a model nobody here can run — it reads as advice."""
    body = client().get("/api/view").json()
    for candidate in body["candidates"]:
        assert candidate["copilot"], f"{candidate['label']} is not sold by Copilot"
        assert candidate["available"] is True
    for by_patience in body["plans"].values():
        for role in (r for plan in by_patience.values() for r in plan["roles"].values()):
            if role.get("pick"):
                assert role["pick"]["copilot"], f"{role['pick']['label']} cannot be started here"
    for candidate in body["excluded"]:
        assert candidate["unavailable_reason"] in {"not in Copilot", "not enabled for us"}


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


def test_recommendations_are_served_from_the_archive():
    from kvasir import recommend

    api = client()
    assert api.get("/api/recommendations").json()["points"] == []  # nothing captured yet
    assert recommend.capture(settings.db_path, settings) is True
    body = api.get("/api/recommendations").json()
    assert len(body["points"]) == 1
    plans = body["points"][0]["plans"]
    assert set(plans) == {"basic", "heavy", "power"}
    for by_patience in plans.values():
        for roles in by_patience.values():
            assert set(roles) == {"architect", "worker", "scout"}
            for pick in roles.values():
                assert pick["key"] and pick["effort"]


def test_the_api_key_survives_a_container_rebuild():
    """The key vanished once because it lived only in an env var one rebuild path sets."""
    import os
    import tempfile

    from kvasir.config import Settings, _secret

    data_dir = tempfile.mkdtemp(prefix="kvasir-secret-")
    assert _secret("KVASIR_STUPIDLEVEL_API_KEY", data_dir) == ""

    with open(os.path.join(data_dir, "secrets.env"), "w", encoding="utf-8") as handle:
        handle.write("# written by the deploy script\nKVASIR_STUPIDLEVEL_API_KEY=asl_live_file\n")
    assert _secret("KVASIR_STUPIDLEVEL_API_KEY", data_dir) == "asl_live_file"

    with open(os.path.join(data_dir, "stupidlevel_api_key.key"), "w", encoding="utf-8") as handle:
        handle.write("asl_live_bare\n")
    assert _secret("KVASIR_STUPIDLEVEL_API_KEY", data_dir) == "asl_live_bare"

    os.environ["KVASIR_STUPIDLEVEL_API_KEY"] = "asl_live_env"
    try:
        assert _secret("KVASIR_STUPIDLEVEL_API_KEY", data_dir) == "asl_live_env"
        assert Settings().stupidlevel_api_key == "asl_live_env"
    finally:
        del os.environ["KVASIR_STUPIDLEVEL_API_KEY"]


def test_two_ticks_at_once_poll_each_source_once(monkeypatch):
    """Boot used to poll every source twice: a tick that waited for another collection then
    collected the list it had decided on before waiting. "Due" is decided under the lock now."""
    import asyncio
    import tempfile

    from kvasir import scheduler
    from kvasir.collectors import MODULES
    from kvasir.config import Settings

    local = Settings(data_dir=tempfile.mkdtemp(prefix="kvasir-tick-"))
    db.init(local.db_path)
    monkeypatch.setattr(scheduler, "settings", local)
    polled = []

    async def fake_collect(source, http):
        polled.append(source)
        await asyncio.sleep(0.01)  # long enough for the other tick to queue on the lock
        db.log_run(local.db_path, source, db.now_iso(), True, False, 1, None, None)

    async def fake_backfill(http):
        polled.append("backfill")
        db.log_run(local.db_path, scheduler.BACKFILL_SOURCE, db.now_iso(), True, False, 1, None, None)

    monkeypatch.setattr(scheduler, "collect_source", fake_collect)
    monkeypatch.setattr(scheduler, "backfill_drift", fake_backfill)
    monkeypatch.setattr(scheduler, "capture_recommendation", lambda: False)

    async def both():
        await asyncio.gather(scheduler.tick(), scheduler.tick())

    asyncio.run(both())
    assert sorted(polled) == sorted([*MODULES, "backfill"])


def test_the_changelog_names_the_version_and_only_real_places():
    """The version is the newest entry; every "show me" opens a tab and a chart that exist."""
    import pathlib
    import re

    from kvasir import changelog

    body = client().get("/api/changelog").json()
    assert body["version"] == changelog.VERSION == body["entries"][0]["version"]
    assert client().get("/api/view").json()["version"] == changelog.VERSION

    versions = [entry["version"] for entry in changelog.CHANGELOG]
    assert len(versions) == len(set(versions))
    dates = [entry["date"] for entry in changelog.CHANGELOG]
    assert dates == sorted(dates, reverse=True)

    page = (pathlib.Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    panels = set(re.findall(r'\{ id: "([a-z]+)", label:', page))
    assert panels == changelog.PANELS
    for entry in changelog.CHANGELOG:
        assert entry["title"] and entry["items"]
        for item in entry["items"]:
            where = item.get("where")
            if where:
                assert where["panel"] in panels
                assert where.get("map", "cost") in changelog.MAPS
