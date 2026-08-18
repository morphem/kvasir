"""The HTTP surface, served from an archive the test filled in."""

from conftest import fixture
from fastapi.testclient import TestClient

from kvasir import db
from kvasir.api import app
from kvasir.collectors import copilot, cursorbench, stupidlevel
from kvasir.config import settings


def seed():
    db.init(settings.db_path)
    for module, name in (
        (cursorbench, "cursorbench.html"),
        (copilot, "copilot-models-and-pricing.html"),
        (stupidlevel, "stupidlevel-scores.json"),
    ):
        rows, meta = module.parse(fixture(name))
        db.archive(settings.db_path, module.SOURCE, rows, meta)


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


def test_the_page_itself_is_served():
    response = client().get("/")
    assert response.status_code == 200
    assert "Kvasir" in response.text
