"""The verdict layer: same three sources in, one decision out."""

from conftest import fixture

from kvasir.collectors import copilot, cursorbench, stupidlevel
from kvasir.config import Settings
from kvasir import recommend


def build(hidden=None):
    cb, _ = cursorbench.parse(fixture("cursorbench.html"))
    ai, _ = stupidlevel.parse(fixture("stupidlevel-scores.json"))
    cp, _ = copilot.parse(fixture("copilot-models-and-pricing.html"))
    settings = Settings()
    return recommend.build(cb, ai, cp, settings, hidden if hidden is not None else [])


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


def test_hidden_models_leave_the_view_but_stay_in_the_data():
    everything = build()
    filtered = build(hidden=["grok-4.6", "fable-5"])
    assert any(c["key"] == "grok-4.6" for c in everything["candidates"])
    assert not any(c["key"] in {"grok-4.6", "fable-5"} for c in filtered["candidates"])
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
    ai = [
        {"model_key": "falling", "score": 40, "trend": "down", "status": "warning", "is_stale": False},
        {"model_key": "steady", "score": 70, "trend": "stable", "status": "good", "is_stale": False},
    ]
    view = recommend.build(cb, ai, [], Settings(), [])
    worker = view["verdicts"]["worker"]
    assert worker["pick"]["key"] == "steady"
    assert worker["replaced"]["key"] == "falling"
    assert "dryfuje" in worker["why"]


def test_overlapping_tiers_are_named_once():
    """When two roles land on the same model, say so instead of inventing a difference."""
    cb = [
        {"model_key": "only", "effort": "high", "rank": 1, "score": 60.0,
         "cost_uusd": 100_000, "tokens": 1000, "steps": 10},
    ]
    view = recommend.build(cb, [], [], Settings(), [])
    assert view["verdicts"]["worker"]["overlap_with"] == "architect"
    assert "pokrywają" in view["verdicts"]["worker"]["overlap_note"]


def test_tasks_resolve_to_a_named_model():
    view = build()
    assert len(view["tasks"]) >= 10
    for task in view["tasks"]:
        assert task["pick_label"]
        assert task["tier"] in {"architect", "worker", "scout"}
