"""The credit layer: a month of work, priced in AI credits, against a tier.

These tests pin the arithmetic and the discipline, not the specific models — the models are
whatever the live data says this week. Every rule is checked at every patience setting.
"""

from datetime import datetime, timezone

from conftest import fixture, september_board
from test_recommend import aa_row, sold

from kvasir import budget, recommend
from kvasir.collectors import artificialanalysis, copilot, stupidlevel
from kvasir.config import Settings


def view(tiers=None):
    aa, _ = september_board()
    ai, _ = stupidlevel.parse(fixture("stupidlevel-scores.json"))
    cp, cp_meta = copilot.parse(fixture("copilot-models-and-pricing.html"))
    settings = Settings()
    if tiers:
        settings = Settings(tiers=tiers)
    return recommend.build(
        aa, ai, cp, settings, settings.disabled_models, credit_usd=cp_meta.get("credit_usd")
    )


def every_plan(payload):
    """Each tier at each patience setting — nine plans on the default tiers."""
    for by_patience in payload["plans"].values():
        yield from by_patience.values()


def test_credit_rate_comes_from_the_docs_not_from_a_constant():
    """1 AI credit = $0.01 is GitHub's statement; the page must quote it, not assume it."""
    _, meta = copilot.parse(fixture("copilot-models-and-pricing.html"))
    assert meta["credit_usd"] == 0.01
    assert "1 AI credit" in meta["credit_usd_quote"]

    payload = view()
    assert payload["credit_usd"] == 0.01
    assert payload["credit_usd_verified"] is True


def test_credits_are_dollars_times_one_hundred():
    assert budget.credits_for(2_310_000, 0.01) == 231.0
    assert budget.credits_for(390_000, 0.01) == 39.0
    assert budget.credits_for(None, 0.01) is None


def test_every_tier_gets_a_full_plan_that_states_its_arithmetic():
    payload = view()
    for tier in payload["budget_tiers"]:
        plan = payload["plans"][tier["id"]][budget.DEFAULT_PATIENCE]
        assert plan["usd"] == round(tier["credits"] * 0.01, 2)
        assert set(plan["roles"]) == {"architect", "worker", "subagent"}
        rebuilt = sum(
            role["month_credits"] for name, role in plan["roles"].items()
            if role["pick"] and name != "subagent"
        )
        assert abs(rebuilt - plan["month_credits"]) <= 2  # rounding only
        for role in plan["roles"].values():
            assert role["why"]


def test_a_tight_tier_buys_cheaper_models_than_a_generous_one():
    payload = view()
    basic = payload["plans"]["basic"][budget.DEFAULT_PATIENCE]
    power = payload["plans"]["power"][budget.DEFAULT_PATIENCE]
    assert basic["roles"]["architect"]["per_task_credits"] < power["roles"]["architect"]["per_task_credits"]
    assert power["roles"]["architect"]["out_of_reach"] is None  # nothing is out of reach here
    assert basic["month_credits"] < power["month_credits"]


def test_the_plan_fits_the_month_it_was_built_for():
    for plan in every_plan(view()):
        assert plan["month_credits"] <= plan["credits"], f"{plan['name']} overspends its own tier"


def test_a_tier_too_small_for_anything_says_so():
    payload = view(tiers=[{"id": "sliver", "name": "Sliver", "credits": 10}])
    roles = payload["plans"]["sliver"][budget.DEFAULT_PATIENCE]["roles"]
    base = [roles[name] for name in ("architect", "worker")]
    assert all(role["pick"] is None for role in base)
    assert all("Nothing on the board" in role["why"] for role in base)


def test_the_mechanical_role_never_outranks_the_planning_one():
    """However much budget there is, the stack keeps its shape."""
    payload = view(tiers=[{"id": "silly", "name": "Silly", "credits": 5_000_000}])
    for plan in payload["plans"]["silly"].values():
        roles = plan["roles"]
        assert roles["worker"]["pick"]["score"] <= roles["architect"]["pick"]["score"]
        assert roles["worker"]["pick"]["cost_uusd"] <= roles["architect"]["pick"]["cost_uusd"]


def test_a_role_you_iterate_with_never_outlasts_its_patience():
    """The architect may be slow — a plan is made once, deliberately. The loop roles may not."""
    for plan in every_plan(view()):
        ceilings = budget.PATIENCE[plan["patience"]]
        for name in ("worker", "subagent"):
            pick = plan["roles"][name]["pick"]
            minutes = budget.loop_minutes(pick) if pick else None
            if minutes is not None and ceilings["worker"] is not None:
                assert minutes <= ceilings["worker"], f"{name} takes {minutes} min at {plan['patience']}"


def test_an_untimed_variant_cannot_promise_a_ceiling():
    """A ceiling is a promise about time; only Any pace, which makes none, lets it compete."""
    untimed = {"key": "mystery", "effort": "max", "score": 60.0, "cost_uusd": 1_000_000}
    assert not budget.quick_enough(untimed, 3)
    assert budget.quick_enough(untimed, None)
    assert budget.quick_enough({**untimed, "speed": {"task_minutes": 2}}, 3)
    assert not budget.quick_enough({**untimed, "speed": {"task_minutes": 8}}, 3)
    assert budget.quick_enough({**untimed, "speed": {"task_minutes": 40}}, None)


def test_an_untimed_model_takes_no_loop_seat_under_a_ceiling_and_is_named():
    """Gemini 4 Argon · High, scored and priced but never timed, once took the Fast worker's
    seat. Under a ceiling it no longer does, and the worker's card says why."""
    rows = [
        aa_row("planner", "max", 60.0, 2_000_000, minutes=10),
        aa_row("argon", "high", 55.0, 400_000),
        aa_row("quick", "medium", 48.0, 200_000, minutes=1),
    ]
    view = recommend.build(rows, [], sold("planner", "argon", "quick"), Settings(), [])
    fast = view["plans"]["heavy"]["fast"]["roles"]
    assert fast["worker"]["pick"]["key"] == "quick"
    assert "Argon · High" in fast["worker"]["why"] and "not timed" in fast["worker"]["why"]
    assert view["plans"]["basic"]["any"]["roles"]["worker"]["pick"]["key"] == "argon"


def test_assumptions_are_published_with_the_answer():
    payload = view()
    assumptions = payload["assumptions"]
    assert assumptions["tasks_per_month"] == budget.WORKING_DAYS * budget.TASKS_PER_DAY
    assert sum(assumptions["role_mix"].values()) == 1.0
    assert sum(assumptions["budget_shares"].values()) == 1.0
    assert assumptions["overhead"] >= 1.0


def test_the_drift_veto_applies_inside_a_tier_plan_too():
    """Affordability decides what is possible; drift still decides what is sane."""
    rows = [
        aa_row("falling", "high", 60.0, 1_000_000),
        aa_row("steady", "high", 59.0, 1_000_000),
    ]
    now = datetime.now(timezone.utc).isoformat()
    ai = [
        {"model_key": "falling", "score": 40, "trend": "down", "status": "warning",
         "is_stale": False, "last_updated": now},
        {"model_key": "steady", "score": 70, "trend": "stable", "status": "good",
         "is_stale": False, "last_updated": now},
    ]
    settings = Settings(tiers=[{"id": "roomy", "name": "Roomy", "credits": 1_000_000}])
    payload = recommend.build(rows, ai, [], settings, [], credit_usd=0.01)
    architect = payload["plans"]["roomy"][budget.DEFAULT_PATIENCE]["roles"]["architect"]
    assert architect["pick"]["key"] == "steady"
    assert architect["drift_replaced"] == "Falling · High"
    assert "sliding" in architect["why"]


def test_a_richer_tier_is_never_told_it_fell_short():
    """The card once said "this tier does not reach it" about a model it had outspent."""
    for plan in every_plan(view()):
        name = plan["name"]
        for role, slot in plan["roles"].items():
            reach = slot.get("out_of_reach")
            if not reach:
                continue
            assert role == "architect", f"{name}/{role} should not carry an affordability note"
            # the named model must genuinely cost more than the role's ceiling, and be better
            assert reach["per_task_credits"] > reach["ceiling_credits"]
            assert reach["score"] >= slot["pick"]["score"]


def test_the_spare_allowance_is_reported_as_throughput():
    """Unused credits buy nothing, so the day's allowance past the base day becomes more runs."""
    for plan in every_plan(view()):
        assert plan["day_credits"] == round(plan["credits"] / budget.WORKING_DAYS)
        assert plan["spare_day_credits"] == max(plan["day_credits"] - plan["base_day_credits"], 0) or (
            abs(plan["spare_day_credits"] - (plan["day_credits"] - plan["base_day_credits"])) <= 1
        )
        worker = plan["roles"]["worker"]
        if worker["pick"]:
            price = worker["per_task_credits"] * budget.OVERHEAD
            assert worker["extra_per_day"] == int(plan["spare_day_credits"] / price) or abs(
                worker["extra_per_day"] - plan["spare_day_credits"] / price
            ) <= 1
    heavy = view()["plans"]["heavy"][budget.DEFAULT_PATIENCE]
    power = view()["plans"]["power"][budget.DEFAULT_PATIENCE]
    assert power["extra_per_day"]["worker"] > heavy["extra_per_day"]["worker"]


def agentic_row(key, effort, score, cost_uusd, automation, terminal, minutes=1.0):
    return {**aa_row(key, effort, score, cost_uusd, minutes=minutes),
            "automation_bench": automation, "terminal_bench": terminal}


def test_a_board_without_agentic_scores_says_so_instead_of_picking():
    payload = view()
    for plan in every_plan(payload):
        sub = plan["roles"]["subagent"]
        if sub["pick"] is None:
            assert "agentic" in sub["why"]


def test_the_subagent_climbs_the_agentic_ladder_from_the_bar():
    """Chosen on AutomationBench and Terminal-Bench, not the Intelligence Index: from the
    cheapest over the bar, up while an agentic point is fair. v2.12 stopped at the cheapest
    and seated an older model eight points worse for five credits less."""
    rows = [
        agentic_row("smart", "max", 60.0, 20_000_000, 70.0, 60.0, minutes=2),  # leader 65, the architect
        agentic_row("doer", "low", 40.0, 200_000, 60.0, 40.0),                 # 50: over 48.75
        agentic_row("sharper", "medium", 45.0, 300_000, 66.0, 46.0),           # 56 for +$0.10
        agentic_row("clever", "low", 50.0, 150_000, 30.0, 20.0),               # higher index, weak agent
        agentic_row("slowdoer", "low", 40.0, 400_000, 70.0, 50.0, minutes=9),  # 60, fair, too slow
    ]
    view = recommend.build(rows, [], sold(*(r["model_key"] for r in rows)), Settings(), [], credit_usd=0.01)
    sub = view["plans"]["heavy"]["balanced"]["roles"]["subagent"]
    assert sub["pick"]["key"] == "sharper"
    assert sub["agentic_score"] == 56.0
    assert sub["speed_blocked"]["label"].startswith("Slowdoer")
    assert view["plans"]["heavy"]["any"]["roles"]["subagent"]["pick"]["key"] == "slowdoer"


def test_the_worker_card_names_a_quicker_effort_of_its_own_model():
    """The scout's work moved to the worker, at an effort that takes half the time or less."""
    rows = [
        aa_row("planner", "max", 60.0, 2_000_000, minutes=10),
        aa_row("sol", "xhigh", 55.0, 600_000, minutes=5),
        aa_row("sol", "medium", 50.0, 400_000, minutes=3),   # not quick enough: over half
        aa_row("sol", "low", 40.0, 180_000, minutes=1.5),
        aa_row("other", "low", 45.0, 100_000, minutes=1),    # quicker, but another model
    ]
    view = recommend.build(rows, [], sold("planner", "sol", "other"), Settings(), [], credit_usd=0.01)
    worker = view["plans"]["heavy"]["balanced"]["roles"]["worker"]
    assert (worker["pick"]["key"], worker["pick"]["effort"]) == ("sol", "xhigh")
    assert worker["quick"]["label"].endswith("Low")
    assert worker["quick"]["task_minutes"] == 1.5


def test_the_subagent_never_costs_more_than_the_architect():
    """Delegating to a dearer model is not delegation: at Any pace the agentic ladder once
    climbed onto the architect's own variant, at 36 minutes a task."""
    for plan in every_plan(view()):
        roles = plan["roles"]
        sub, arch = roles["subagent"]["pick"], roles["architect"]["pick"]
        if sub and arch:
            assert sub["cost_uusd"] <= arch["cost_uusd"]
            assert (sub["key"], sub["effort"]) != (arch["key"], arch["effort"])
    rows = [
        agentic_row("planner", "max", 60.0, 900_000, 80.0, 70.0, minutes=30),
        agentic_row("doer", "low", 40.0, 200_000, 60.0, 50.0),
    ]
    view_ = recommend.build(rows, [], sold("planner", "doer"), Settings(), [], credit_usd=0.01)
    assert view_["plans"]["heavy"]["any"]["roles"]["subagent"]["pick"]["key"] == "doer"

