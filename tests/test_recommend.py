"""The verdict layer: same three sources in, one decision out."""

import os
import tempfile
from datetime import datetime, timezone

from conftest import fixture

from kvasir import db, recommend
from kvasir.collectors import copilot, cursorbench, stupidlevel
from kvasir.config import Settings


def build(disabled=None):
    cb, _ = cursorbench.parse(fixture("cursorbench.html"))
    ai, _ = stupidlevel.parse(fixture("stupidlevel-scores.json"))
    cp, _ = copilot.parse(fixture("copilot-models-and-pricing.html"))
    settings = Settings()
    disabled = disabled if disabled is not None else settings.disabled_models
    return recommend.build(cb, ai, cp, settings, disabled)


def test_every_tier_gets_a_pick_with_an_effort():
    view = build()
    assert set(view["verdicts"]) == {"architect", "worker", "scout"}
    for verdict in view["verdicts"].values():
        pick = verdict["pick"]
        assert pick["effort"] in {"low", "medium", "high", "xhigh", "max", "default"}
        assert pick["effort_label"] in pick["label"] or pick["effort"] == "default"
        assert verdict["why"]


def test_tiers_are_ordered_by_cost_and_quality():
    view = build()
    architect = view["verdicts"]["architect"]["pick"]
    worker = view["verdicts"]["worker"]["pick"]
    scout = view["verdicts"]["scout"]["pick"]
    assert architect["score"] >= worker["score"] >= scout["score"]
    assert architect["cost_usd"] >= worker["cost_usd"] >= scout["cost_usd"]


def test_thresholds_are_respected():
    view = build()
    settings = Settings()
    assert view["verdicts"]["worker"]["pick"]["cost_usd"] <= settings.worker_max_cost_usd
    assert view["verdicts"]["scout"]["pick"]["cost_usd"] <= settings.scout_max_cost_usd
    top = max(c["score"] for c in view["candidates"])
    assert view["verdicts"]["architect"]["pick"]["score"] >= top - settings.architect_score_slack_pp


def test_disabled_models_leave_the_view_but_stay_in_the_data():
    everything = build(disabled=[])
    filtered = build(disabled=["grok", "fable"])
    assert any(c["key"] == "grok-4.6" for c in everything["candidates"])
    assert not any(c["key"].startswith(("grok", "fable")) for c in filtered["candidates"])
    assert filtered["all_candidates_count"] == everything["all_candidates_count"]


def test_ladder_is_a_real_frontier():
    view = build()
    ladder = view["ladder"]
    assert len(ladder) >= 3
    costs = [rung["cost_usd"] for rung in ladder]
    scores = [rung["score"] for rung in ladder]
    assert costs == sorted(costs)
    assert scores == sorted(scores)  # each rung buys something
    assert all(rung["verdict"] in {"bargain", "fair", "steep"} for rung in ladder[1:])


def test_drift_veto_prefers_a_stable_model():
    """A model trending down loses to a comparable one that is not."""
    cb = [
        {"model_key": "falling", "effort": "high", "rank": 1, "score": 60.0,
         "cost_uusd": 1_000_000, "tokens": 1000, "steps": 10},
        {"model_key": "steady", "effort": "high", "rank": 2, "score": 59.0,
         "cost_uusd": 1_100_000, "tokens": 1000, "steps": 10},
    ]
    now = datetime.now(timezone.utc).isoformat()
    ai = [
        {"model_key": "falling", "score": 40, "trend": "down", "status": "warning",
         "is_stale": False, "last_updated": now},
        {"model_key": "steady", "score": 70, "trend": "stable", "status": "good",
         "is_stale": False, "last_updated": now},
    ]
    view = recommend.build(cb, ai, [], Settings(), [])
    worker = view["verdicts"]["worker"]
    assert worker["pick"]["key"] == "steady"
    assert worker["replaced"]["key"] == "falling"
    assert "drifting down" in worker["why"]


def test_overlapping_tiers_are_named_once():
    """When two roles land on the same model, say so instead of inventing a difference."""
    cb = [
        {"model_key": "only", "effort": "high", "rank": 1, "score": 60.0,
         "cost_uusd": 100_000, "tokens": 1000, "steps": 10},
    ]
    view = recommend.build(cb, [], [], Settings(), [])
    assert view["verdicts"]["worker"]["overlap_with"] == "architect"
    assert "overlap" in view["verdicts"]["worker"]["overlap_note"]


def test_tasks_resolve_to_a_named_model():
    view = build()
    assert len(view["tasks"]) >= 10
    for task in view["tasks"]:
        assert task["pick_label"]
        assert task["tier"] in {"architect", "worker", "scout"}


def seed_archive(path: str) -> None:
    db.init(path)
    for module, name in (
        (cursorbench, "cursorbench.html"),
        (stupidlevel, "stupidlevel-scores.json"),
        (copilot, "copilot-models-and-pricing.html"),
    ):
        rows, meta = module.parse(fixture(name))
        db.archive(path, module.SOURCE, rows, meta)


def test_capture_archives_the_verdict_once_per_change():
    """The page's own answer belongs in the archive — but only when the answer moved."""
    path = os.path.join(tempfile.mkdtemp(prefix="kvasir-rec-"), "kvasir.db")
    seed_archive(path)
    cfg = Settings()
    assert recommend.capture(path, cfg) is True   # the first verdict lands
    assert recommend.capture(path, cfg) is False  # an unchanged verdict writes nothing

    stored = db.recommendation_history(path, days=1)[0]
    expected = build(cfg.disabled_models)["verdicts"]  # the capture filters like the default view
    for tier_id, verdict in stored["verdicts"].items():
        pick = verdict["pick"]
        assert pick["key"] == expected[tier_id]["pick"]["key"]
        assert pick["effort"] == expected[tier_id]["pick"]["effort"]
        assert pick["score"] == expected[tier_id]["pick"]["score"]


def test_capture_refuses_an_incomplete_board():
    """Half the sources is not a verdict; writing one down would be inventing history."""
    path = os.path.join(tempfile.mkdtemp(prefix="kvasir-rec-"), "kvasir.db")
    db.init(path)
    rows, _ = cursorbench.parse(fixture("cursorbench.html"))
    db.archive(path, "cursorbench", rows, {})
    assert recommend.capture(path, Settings()) is False
    assert db.archive_stats(path)["recommendations"] == 0


def test_availability_is_read_from_copilot_not_from_a_list():
    """A model GitHub does not sell is off the board without anyone maintaining an entry."""
    view = build()
    keys = {c["key"] for c in view["candidates"]}
    excluded = {c["key"]: c["unavailable_reason"] for c in view["excluded"]}
    assert "composer-2.5" not in keys
    assert excluded.get("composer-2.5") == "not in Copilot"


def test_disabled_families_cover_point_releases():
    """fable-5.1 arrived after the list said "fable-5", and walked straight into the verdict."""
    assert recommend.in_family("fable-5.1", "fable")
    assert recommend.in_family("fable-5", "fable")
    assert recommend.in_family("grok-4.6", "grok")
    assert recommend.in_family("kimi-k2.7-code", "kimi-k2.7")
    # a family must not swallow its neighbours
    assert not recommend.in_family("kimi-k3", "kimi-k2.7")
    assert not recommend.in_family("gpt-5.6-terra", "gpt-5.6-sol")
    assert not recommend.in_family("sonnet-5", "sonnet-4")


def test_a_disabled_family_never_reaches_a_verdict():
    cb = [
        {"model_key": "fable-5.1", "effort": "max", "rank": 1, "score": 90.0,
         "cost_uusd": 1_000_000, "tokens": 1000, "steps": 10},
        {"model_key": "opus-5", "effort": "max", "rank": 2, "score": 70.0,
         "cost_uusd": 1_000_000, "tokens": 1000, "steps": 10},
    ]
    cp = [
        {"model_key": "fable-5.1", "effort": "default", "tier": "Default",
         "input_uusd": 1, "output_uusd": 1, "category": "Powerful"},
        {"model_key": "opus-5", "effort": "default", "tier": "Default",
         "input_uusd": 1, "output_uusd": 1, "category": "Powerful"},
    ]
    settings = Settings()
    view = recommend.build(cb, [], cp, settings, ["fable"])
    assert {c["key"] for c in view["candidates"]} == {"opus-5"}
    assert view["verdicts"]["architect"]["pick"]["key"] == "opus-5"
    # and it comes back the moment the board is opened
    opened = recommend.build(cb, [], cp, settings, ["fable"], show_all=True)
    assert opened["verdicts"]["architect"]["pick"]["key"] == "fable-5.1"


def _pair(drift_a, drift_b):
    """A dipping favourite and a cheaper rival, with whatever drift records are given."""
    cb = [
        {"model_key": "favourite", "effort": "max", "rank": 1, "score": 70.0,
         "cost_uusd": 1_000_000, "tokens": 1000, "steps": 10},
        {"model_key": "rival", "effort": "max", "rank": 2, "score": 69.0,
         "cost_uusd": 1_000_000, "tokens": 1000, "steps": 10},
    ]
    cp = [
        {"model_key": k, "effort": "default", "tier": "Default",
         "input_uusd": 1, "output_uusd": 1, "category": "Powerful"}
        for k in ("favourite", "rival")
    ]
    ai = [row for row in (drift_a, drift_b) if row]
    return cb, ai, cp


def test_an_unmeasured_model_never_wins_a_drift_veto():
    """Absence of a drift record is not evidence of stability — it beat every measured model."""
    fresh = datetime.now(timezone.utc).isoformat()
    cb, ai, cp = _pair(
        {"model_key": "favourite", "score": 70, "trend": "down", "status": "good",
         "is_stale": False, "last_updated": fresh},
        None,  # the rival is simply not in AI Stupid Level
    )
    view = recommend.build(cb, ai, cp, Settings(), [])
    assert view["verdicts"]["architect"]["pick"]["key"] == "favourite"
    assert view["verdicts"]["architect"]["replaced"] is None


def test_a_measured_steady_model_still_wins_the_veto():
    fresh = datetime.now(timezone.utc).isoformat()
    cb, ai, cp = _pair(
        {"model_key": "favourite", "score": 70, "trend": "down", "status": "good",
         "is_stale": False, "last_updated": fresh},
        {"model_key": "rival", "score": 72, "trend": "stable", "status": "good",
         "is_stale": False, "last_updated": fresh},
    )
    view = recommend.build(cb, ai, cp, Settings(), [])
    assert view["verdicts"]["architect"]["pick"]["key"] == "rival"
    assert view["drift_trusted"] is True


def test_a_frozen_drift_signal_stops_vetoing():
    """A reading from four days ago kept vetoing the same model every hour."""
    old = "2020-01-01T00:00:00+00:00"
    cb, ai, cp = _pair(
        {"model_key": "favourite", "score": 70, "trend": "down", "status": "good",
         "is_stale": False, "last_updated": old},
        {"model_key": "rival", "score": 72, "trend": "stable", "status": "good",
         "is_stale": False, "last_updated": old},
    )
    view = recommend.build(cb, ai, cp, Settings(), [])
    assert view["drift_trusted"] is False
    assert view["drift_age_hours"] > recommend.DRIFT_TRUST_HOURS
    assert view["verdicts"]["architect"]["pick"]["key"] == "favourite"
