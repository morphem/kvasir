"""The verdict layer: three sources in, one board and nine plans out."""

import os
import tempfile
from datetime import datetime, timezone

from conftest import fixture

from kvasir import budget, db, recommend
from kvasir.collectors import artificialanalysis, copilot, stupidlevel
from kvasir.config import Settings


def build(disabled=None, show_all=False):
    aa, _ = artificialanalysis.parse(fixture("artificialanalysis-model-page.html"))
    ai, _ = stupidlevel.parse(fixture("stupidlevel-scores.json"))
    cp, meta = copilot.parse(fixture("copilot-models-and-pricing.html"))
    settings = Settings()
    disabled = disabled if disabled is not None else settings.disabled_models
    return recommend.build(
        aa, ai, cp, settings, disabled, credit_usd=meta.get("credit_usd"), show_all=show_all
    )


def aa_row(key, effort, score, cost_uusd, minutes=None, wait=None, tps=None):
    """One Artificial Analysis variant, with only the fields the verdict reads."""
    return {
        "model_key": key, "effort": effort, "score": score, "cost_uusd": cost_uusd,
        "output_tokens": 1000, "terminal_bench": None, "tokens_per_second": tps,
        "task_seconds": minutes * 60 if minutes is not None else None,
        "first_answer_seconds": wait, "end_to_end_seconds": None, "thinking_seconds": None,
        "deprecated": False, "released": "",
    }


def sold(*keys):
    return [
        {"model_key": k, "effort": "default", "tier": "Default",
         "input_uusd": 1, "output_uusd": 1, "category": "Powerful"}
        for k in keys
    ]


def picks(view, tier="heavy", patience="balanced"):
    return {role: slot["pick"] for role, slot in view["plans"][tier][patience]["roles"].items()}


def test_every_tier_gets_a_pick_with_an_effort():
    """The invariant: no number without the effort it was measured at."""
    view = build()
    assert set(view["plans"]) == {"basic", "heavy", "power"}
    for by_patience in view["plans"].values():
        assert set(by_patience) == set(budget.PATIENCE)
        for plan in by_patience.values():
            for slot in plan["roles"].values():
                pick = slot["pick"]
                assert pick["effort"] in {"low", "medium", "high", "xhigh", "max"}
                assert pick["effort_label"] in pick["label"]
                assert slot["why"]


def test_roles_are_ordered_by_cost_and_quality():
    view = build()
    for by_patience in view["plans"].values():
        for plan in by_patience.values():
            roles = {role: slot["pick"] for role, slot in plan["roles"].items()}
            assert roles["architect"]["score"] >= roles["worker"]["score"] >= roles["scout"]["score"]
            assert (
                roles["architect"]["cost_uusd"]
                >= roles["worker"]["cost_uusd"]
                >= roles["scout"]["cost_uusd"]
            )


def test_the_new_releases_reach_the_board():
    """Opus 5.5, GPT-6 Luna and GPT-6 Sol are sold by Copilot and scored by the source."""
    view = build()
    keys = {c["key"] for c in view["candidates"]}
    assert {"opus-5.5", "gpt-6-luna", "gpt-6-sol"} <= keys


def test_an_unpriced_variant_is_shown_but_never_planned():
    """GPT-6 shipped timed but not priced; a budget cannot be planned on no price."""
    view = build()
    luna = [c for c in view["candidates"] if c["key"] == "gpt-6-luna"]
    assert luna and not any(c["priced"] for c in luna)
    assert any(u["key"] == "gpt-6-luna" for u in view["unpriced"])
    assert all(rung["key"] != "gpt-6-luna" for rung in view["ladder"])
    for by_patience in view["plans"].values():
        for plan in by_patience.values():
            assert all(slot["pick"]["key"] != "gpt-6-luna" for slot in plan["roles"].values())


def test_non_reasoning_variants_never_reach_the_board():
    """A variant with no named effort is archived, not shown as a candidate."""
    view = build(show_all=True)
    assert all(c["effort"] != "default" for c in view["candidates"])


def test_disabled_models_leave_the_view_but_stay_in_the_data():
    everything = build(disabled=[])
    filtered = build(disabled=["grok", "fable"])
    assert any(c["key"] == "grok-4.7" for c in everything["candidates"])
    assert not any(c["key"].startswith(("grok", "fable")) for c in filtered["candidates"])
    assert filtered["all_candidates_count"] == everything["all_candidates_count"]


def test_gpt_6_astra_is_switched_off_by_default():
    view = build()
    assert not any(c["key"] == "gpt-6-astra" for c in view["candidates"])
    reasons = {c["key"]: c["unavailable_reason"] for c in view["excluded"]}
    assert reasons.get("gpt-6-astra") == "not enabled for us"


def test_ladder_is_a_real_frontier():
    view = build()
    ladder = view["ladder"]
    assert len(ladder) >= 3
    costs = [rung["cost_usd"] for rung in ladder]
    scores = [rung["score"] for rung in ladder]
    assert costs == sorted(costs)
    assert scores == sorted(scores)  # each rung buys something
    assert all(rung["verdict"] in {"bargain", "fair", "steep"} for rung in ladder[1:])


def test_a_single_model_is_named_once():
    """When two roles land on the same variant, say so instead of inventing a difference."""
    view = recommend.build([aa_row("only", "high", 60.0, 100_000)], [], sold("only"), Settings(), [])
    roles = view["plans"]["heavy"]["balanced"]["roles"]
    assert roles["worker"]["same_as"] == "architect"
    assert roles["scout"]["same_as"] == "worker"


def test_tasks_carry_their_role():
    view = build()
    assert len(view["tasks"]) >= 10
    for task in view["tasks"]:
        assert task["tier"] in {"architect", "worker", "scout"}
        assert task["tier_name"]


def test_patience_decides_the_loop_roles_only():
    """A model that takes ten minutes a task loses the scout's seat at Fast, never the architect's."""
    rows = [
        aa_row("thinker", "max", 60.0, 300_000, minutes=10),
        aa_row("quick", "low", 40.0, 100_000, minutes=1),
    ]
    view = recommend.build(rows, [], sold("thinker", "quick"), Settings(), [])
    fast = picks(view, "basic", "fast")
    anything = picks(view, "basic", "any")
    assert fast["scout"]["key"] == "quick"
    assert fast["architect"]["key"] == "thinker"
    assert anything["scout"]["key"] == "thinker"


def seed_archive(path: str) -> None:
    db.init(path)
    for module, name in (
        (artificialanalysis, "artificialanalysis-model-page.html"),
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
    expected = build(cfg.disabled_models)["plans"]  # the capture filters like the default view
    for tier_id, by_patience in stored["plans"].items():
        for patience_id, roles in by_patience.items():
            for role, pick in roles.items():
                want = expected[tier_id][patience_id]["roles"][role]["pick"]
                assert (pick["key"], pick["effort"], pick["score"]) == (
                    want["key"], want["effort"], want["score"]
                )


def test_capture_refuses_an_incomplete_board():
    """Half the sources is not a verdict; writing one down would be inventing history."""
    path = os.path.join(tempfile.mkdtemp(prefix="kvasir-rec-"), "kvasir.db")
    db.init(path)
    rows, _ = artificialanalysis.parse(fixture("artificialanalysis-model-page.html"))
    db.archive(path, "artificialanalysis", rows, {})
    assert recommend.capture(path, Settings()) is False
    assert db.archive_stats(path)["recommendations"] == 0


def test_availability_is_read_from_copilot_not_from_a_list():
    """A model GitHub does not sell is off the board without anyone maintaining an entry."""
    view = build()
    assert not any(c["key"].startswith("muse-spark") for c in view["candidates"])
    opened = build(show_all=True)
    muse = [c for c in opened["candidates"] if c["key"].startswith("muse-spark")]
    assert muse and all(c["unavailable_reason"] == "not in Copilot" for c in muse)


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
    assert not recommend.in_family("gpt-6-sol", "gpt-6-astra")


def test_a_disabled_family_never_reaches_a_verdict():
    rows = [aa_row("fable-5.1", "max", 90.0, 1_000_000), aa_row("opus-5", "max", 70.0, 1_000_000)]
    settings = Settings()
    view = recommend.build(rows, [], sold("fable-5.1", "opus-5"), settings, ["fable"])
    assert {c["key"] for c in view["candidates"]} == {"opus-5"}
    assert picks(view)["architect"]["key"] == "opus-5"
    # and it comes back the moment the board is opened
    opened = recommend.build(rows, [], sold("fable-5.1", "opus-5"), settings, ["fable"], show_all=True)
    assert picks(opened)["architect"]["key"] == "fable-5.1"


def _pair(drift_a, drift_b):
    """A dipping favourite and a rival of the same price, with whatever drift is given."""
    rows = [
        aa_row("favourite", "max", 70.0, 1_000_000),
        aa_row("rival", "max", 69.0, 1_000_000),
    ]
    ai = [row for row in (drift_a, drift_b) if row]
    return rows, ai, sold("favourite", "rival")


def test_drift_veto_prefers_a_stable_model():
    fresh = datetime.now(timezone.utc).isoformat()
    rows, ai, cp = _pair(
        {"model_key": "favourite", "score": 70, "trend": "down", "status": "good",
         "is_stale": False, "last_updated": fresh},
        {"model_key": "rival", "score": 72, "trend": "stable", "status": "good",
         "is_stale": False, "last_updated": fresh},
    )
    view = recommend.build(rows, ai, cp, Settings(), [])
    architect = view["plans"]["heavy"]["balanced"]["roles"]["architect"]
    assert architect["pick"]["key"] == "rival"
    assert architect["drift_replaced"] == "Favourite · Max"
    assert view["drift_trusted"] is True


def test_an_unmeasured_model_never_wins_a_drift_veto():
    """Absence of a drift record is not evidence of stability — it beat every measured model."""
    fresh = datetime.now(timezone.utc).isoformat()
    rows, ai, cp = _pair(
        {"model_key": "favourite", "score": 70, "trend": "down", "status": "good",
         "is_stale": False, "last_updated": fresh},
        None,  # the rival is simply not in AI Stupid Level
    )
    view = recommend.build(rows, ai, cp, Settings(), [])
    architect = view["plans"]["heavy"]["balanced"]["roles"]["architect"]
    assert architect["pick"]["key"] == "favourite"
    assert architect["drift_replaced"] is None


def test_a_frozen_drift_signal_stops_vetoing():
    """A reading from four days ago kept vetoing the same model every hour."""
    old = "2020-01-01T00:00:00+00:00"
    rows, ai, cp = _pair(
        {"model_key": "favourite", "score": 70, "trend": "down", "status": "good",
         "is_stale": False, "last_updated": old},
        {"model_key": "rival", "score": 72, "trend": "stable", "status": "good",
         "is_stale": False, "last_updated": old},
    )
    view = recommend.build(rows, ai, cp, Settings(), [])
    assert view["drift_trusted"] is False
    assert view["drift_age_hours"] > recommend.DRIFT_TRUST_HOURS
    assert picks(view)["architect"]["key"] == "favourite"


def test_speed_is_the_variants_own_and_typing_speed_is_lent_with_its_source():
    """Waiting is never borrowed across efforts; typing speed is, and says where from."""
    rows = [
        aa_row("m", "high", 50.0, 1_000_000, minutes=4, wait=12, tps=85),
        aa_row("m", "max", 55.0, 2_000_000),
    ]
    view = recommend.build(rows, [], sold("m"), Settings(), [])
    by_effort = {c["effort"]: c["speed"] for c in view["candidates"]}
    assert by_effort["high"]["first_answer_seconds"] == 12
    assert by_effort["max"]["first_answer_seconds"] is None
    assert by_effort["max"]["tokens_per_second"] == 85
    assert by_effort["max"]["measured_effort"] == "high"


def test_an_untimed_effort_takes_at_least_as_long_as_the_timed_one_below_it():
    """Opus 5.5 · Max, untimed, walked into a Fast worker's seat the day its High crossed the
    ceiling — the slowest variant on the board, passed as "not measured"."""
    rows = [
        aa_row("m", "low", 40.0, 500_000, minutes=1),
        aa_row("m", "xhigh", 55.0, 3_000_000, minutes=8),
        aa_row("m", "max", 58.0, 6_000_000),          # no time of its own
        aa_row("lone", "max", 45.0, 1_000_000),       # no timed effort at all
    ]
    view = recommend.build(rows, [], sold("m", "lone"), Settings(), [])
    speed = {(c["key"], c["effort"]): c["speed"] for c in view["candidates"]}
    assert speed[("m", "max")]["task_minutes"] == 8
    assert speed[("m", "max")]["task_minutes_floor_from"] == "xhigh"
    assert speed[("m", "low")]["task_minutes_floor_from"] is None
    assert speed[("lone", "max")] is None  # absence of evidence still decides nothing
    for by_patience in view["plans"].values():
        for patience_id in ("fast", "balanced"):
            worker = by_patience[patience_id]["roles"]["worker"]["pick"]
            assert (worker["key"], worker["effort"]) != ("m", "max")


def test_the_market_is_listed_for_scale_and_never_planned():
    view = build()
    market = {m["key"] for m in view["market"]}
    assert market and not market & {c["key"] for c in view["candidates"]}
    assert all(m["reason"] for m in view["market"])
