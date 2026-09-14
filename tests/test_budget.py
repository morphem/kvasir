"""The credit layer: a month of work, priced in AI credits, against a tier.

These tests pin the arithmetic and the discipline, not the specific models — the models are
whatever the live data says this week.
"""

from datetime import datetime, timezone

from conftest import fixture

from kvasir import budget, recommend
from kvasir.collectors import copilot, cursorbench, speed, stupidlevel
from kvasir.config import Settings


def view(tiers=None):
    cb, _ = cursorbench.parse(fixture("cursorbench.html"))
    ai, _ = stupidlevel.parse(fixture("stupidlevel-scores.json"))
    cp, cp_meta = copilot.parse(fixture("copilot-models-and-pricing.html"))
    sp, _ = speed.parse(fixture("artificialanalysis-models.html"))
    settings = Settings()
    if tiers:
        settings = Settings(tiers=tiers)
    return recommend.build(
        cb,
        ai,
        cp,
        settings,
        settings.disabled_models,
        credit_usd=cp_meta.get("credit_usd"),
        speed_rows=sp,
    )


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
        plan = payload["plans"][tier["id"]]
        assert plan["usd"] == round(tier["credits"] * 0.01, 2)
        assert set(plan["roles"]) == {"architect", "worker", "scout"}
        rebuilt = sum(role["month_credits"] for role in plan["roles"].values() if role["pick"])
        assert abs(rebuilt - plan["month_credits"]) <= 2  # rounding only
        for role in plan["roles"].values():
            assert role["why"]


def test_a_tight_tier_buys_cheaper_models_than_a_generous_one():
    payload = view()
    basic = payload["plans"]["basic"]
    power = payload["plans"]["power"]
    assert basic["roles"]["architect"]["per_task_credits"] < power["roles"]["architect"]["per_task_credits"]
    assert power["roles"]["architect"]["out_of_reach"] is None  # nothing is out of reach here
    assert basic["month_credits"] < power["month_credits"]


def test_the_plan_fits_the_month_it_was_built_for():
    payload = view()
    for plan in payload["plans"].values():
        assert plan["month_credits"] <= plan["credits"], f"{plan['name']} overspends its own tier"
        assert plan["headroom_credits"] >= 0


def test_a_tier_too_small_for_anything_says_so():
    payload = view(tiers=[{"id": "sliver", "name": "Sliver", "credits": 10}])
    roles = payload["plans"]["sliver"]["roles"]
    assert all(role["pick"] is None for role in roles.values())
    assert all("Nothing on the board" in role["why"] for role in roles.values())


def test_the_mechanical_role_never_outranks_the_planning_one():
    """However much budget there is, the stack keeps its shape."""
    payload = view(tiers=[{"id": "silly", "name": "Silly", "credits": 5_000_000}])
    plan = payload["plans"]["silly"]
    roles = plan["roles"]
    assert roles["scout"]["pick"]["score"] <= roles["worker"]["pick"]["score"]
    assert roles["worker"]["pick"]["score"] <= roles["architect"]["pick"]["score"]
    assert roles["scout"]["pick"]["cost_uusd"] <= roles["architect"]["pick"]["cost_uusd"]
    # A budget the board cannot absorb is not spent for the sake of spending it.
    assert plan["used_pct"] < 100 * budget.MAX_UTILISATION


def test_a_tier_is_used_or_says_what_stopped_it():
    """Unused credits buy nothing. Stopping short is allowed; stopping silently is not."""
    for plan in view()["plans"].values():
        if plan["used_pct"] >= 100 * budget.TARGET_UTILISATION:
            assert plan["stopped_because"] is None
            continue
        assert plan["stopped_because"] in budget.STOP_REASONS
        assert plan["stopped_note"]


def test_the_surplus_walk_runs_or_says_why_it_did_not():
    """Either the tier gets used, or the plan names what stopped it. Never neither."""
    for plan in view()["plans"].values():
        moved = any(role.get("upgraded_from") for role in plan["roles"].values())
        assert moved or plan["stopped_because"], f"{plan['name']} neither spent nor explained"


def test_a_slow_model_cannot_take_a_role_you_wait_on():
    """The architect may be slow — you wait once, deliberately. The loop roles may not."""
    for plan in view()["plans"].values():
        for name in ("worker", "scout"):
            pick = plan["roles"][name]["pick"]
            if not pick:
                continue
            speed = (pick.get("speed") or {}).get("tokens_per_second")
            if speed is not None:
                assert speed >= budget.SPEED_FLOOR_TPS, f"{name} runs at {speed} tokens/s"


def test_an_unmeasured_model_is_not_treated_as_slow():
    """Absence of a measurement decides nothing — the same rule the drift veto learned."""
    unmeasured = {"key": "mystery", "effort": "max", "score": 60.0, "cost_uusd": 1_000_000}
    assert budget.fast_enough(unmeasured)
    assert budget.fast_enough({**unmeasured, "speed": {"tokens_per_second": 500}})
    assert not budget.fast_enough({**unmeasured, "speed": {"tokens_per_second": 5}})


def test_no_plan_ever_passes_the_safety_cap():
    """The month is a model, not a meter — leave room for a heavier one."""
    for plan in view()["plans"].values():
        assert plan["month_credits"] <= plan["credits"] * budget.MAX_UTILISATION + 1


def test_surplus_reaches_planning_before_the_mechanical_role():
    """Cheapest-point buying once put an Opus on the scout while the worker was still light.

    Built rather than observed: every role is given the same affordable ladder and enough
    budget for exactly one step, so which role takes it is the rule under test and nothing
    else.
    """
    ladder = []
    # Sized so the opening shares cannot reach the top rung but the tier's surplus can —
    # otherwise every role starts at the top and there is nothing to order.
    for index, (score, cost) in enumerate([(50.0, 1_000_000), (55.0, 3_000_000), (60.0, 30_000_000)]):
        ladder.append(
            {"model_key": f"rung{index}", "effort": "max", "rank": index + 1, "score": score,
             "cost_uusd": cost, "tokens_per_second": 500, "tokens": 1000, "steps": 10}
        )
    cb = [{k: v for k, v in rung.items() if k != "tokens_per_second"} for rung in ladder]
    cp = [
        {"model_key": rung["model_key"], "effort": "default", "tier": "Default",
         "input_uusd": 1, "output_uusd": 1, "category": "Powerful"}
        for rung in ladder
    ]
    fast = [
        {"model_key": rung["model_key"], "effort": "max", "source_name": rung["model_key"],
         "tokens_per_second": 500.0}
        for rung in ladder
    ]
    settings = Settings(tiers=[{"id": "one_step", "name": "One step", "credits": 100_000}])
    plan = recommend.build(
        cb, [], cp, settings, [], credit_usd=0.01, speed_rows=fast
    )["plans"]["one_step"]
    roles = plan["roles"]
    assert roles["architect"]["upgraded_from"], "the surplus skipped planning"
    assert not roles["scout"]["upgraded_from"], "the mechanical role was served first"


def test_spending_the_surplus_keeps_three_distinct_roles():
    for plan in view()["plans"].values():
        picks = [
            (role["pick"]["key"], role["pick"]["effort"])
            for role in plan["roles"].values()
            if role["pick"] and role.get("upgraded_from")
        ]
        assert len(picks) == len(set(picks)), "a bought-up role landed on another role's model"


def test_assumptions_are_published_with_the_answer():
    payload = view()
    assumptions = payload["assumptions"]
    assert assumptions["tasks_per_month"] == budget.WORKING_DAYS * budget.TASKS_PER_DAY
    assert sum(assumptions["role_mix"].values()) == 1.0
    assert sum(assumptions["budget_shares"].values()) == 1.0
    assert assumptions["overhead"] >= 1.0


def test_the_drift_veto_applies_inside_a_tier_plan_too():
    """Affordability decides what is possible; drift still decides what is sane."""
    cb = [
        {"model_key": "falling", "effort": "high", "rank": 1, "score": 60.0,
         "cost_uusd": 1_000_000, "tokens": 1000, "steps": 10},
        {"model_key": "steady", "effort": "high", "rank": 2, "score": 59.0,
         "cost_uusd": 1_000_000, "tokens": 1000, "steps": 10},
    ]
    now = datetime.now(timezone.utc).isoformat()
    ai = [
        {"model_key": "falling", "score": 40, "trend": "down", "status": "warning",
         "is_stale": False, "last_updated": now},
        {"model_key": "steady", "score": 70, "trend": "stable", "status": "good",
         "is_stale": False, "last_updated": now},
    ]
    settings = Settings(tiers=[{"id": "roomy", "name": "Roomy", "credits": 1_000_000}])
    payload = recommend.build(cb, ai, [], settings, [], credit_usd=0.01)
    architect = payload["plans"]["roomy"]["roles"]["architect"]
    assert architect["pick"]["key"] == "steady"
    assert architect["drift_replaced"] == "Falling · High"
    assert "sliding" in architect["why"]


def test_a_richer_tier_is_never_told_it_fell_short():
    """The card once said "this tier does not reach it" about a model it had outspent."""
    payload = view()
    for name, plan in payload["plans"].items():
        for role, slot in plan["roles"].items():
            reach = slot.get("out_of_reach")
            if not reach:
                continue
            assert role == "architect", f"{name}/{role} should not carry an affordability note"
            # the named model must genuinely cost more than the role's ceiling, and be better
            assert reach["per_task_credits"] > reach["ceiling_credits"]
            assert reach["score"] >= slot["pick"]["score"]
