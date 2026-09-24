"""The credit layer: a month of work, priced in AI credits, against a tier.

These tests pin the arithmetic and the discipline, not the specific models — the models are
whatever the live data says this week. Every rule is checked at every patience setting.
"""

from datetime import datetime, timezone

from conftest import fixture
from test_recommend import aa_row, sold

from kvasir import budget, recommend
from kvasir.collectors import artificialanalysis, copilot, stupidlevel
from kvasir.config import Settings


def view(tiers=None):
    aa, _ = artificialanalysis.parse(fixture("artificialanalysis-model-page.html"))
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
        assert set(plan["roles"]) == {"architect", "worker", "scout"}
        rebuilt = sum(role["month_credits"] for role in plan["roles"].values() if role["pick"])
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
        assert plan["headroom_credits"] >= 0


def test_a_tier_too_small_for_anything_says_so():
    payload = view(tiers=[{"id": "sliver", "name": "Sliver", "credits": 10}])
    roles = payload["plans"]["sliver"][budget.DEFAULT_PATIENCE]["roles"]
    assert all(role["pick"] is None for role in roles.values())
    assert all("Nothing on the board" in role["why"] for role in roles.values())


def test_the_mechanical_role_never_outranks_the_planning_one():
    """However much budget there is, the stack keeps its shape."""
    payload = view(tiers=[{"id": "silly", "name": "Silly", "credits": 5_000_000}])
    for plan in payload["plans"]["silly"].values():
        roles = plan["roles"]
        assert roles["scout"]["pick"]["score"] <= roles["worker"]["pick"]["score"]
        assert roles["worker"]["pick"]["score"] <= roles["architect"]["pick"]["score"]
        # ...and on price: a scout dearer than the worker is a worse worker, not a scout.
        assert roles["scout"]["pick"]["cost_uusd"] <= roles["worker"]["pick"]["cost_uusd"]
        assert roles["worker"]["pick"]["cost_uusd"] <= roles["architect"]["pick"]["cost_uusd"]
        # A budget the board cannot absorb is not spent for the sake of spending it.
        assert plan["used_pct"] < 100 * budget.MAX_UTILISATION


def test_a_tier_is_used_or_says_what_stopped_it():
    """Unused credits buy nothing. Stopping short is allowed; stopping silently is not."""
    for plan in every_plan(view()):
        if plan["used_pct"] >= 100 * budget.TARGET_UTILISATION:
            assert plan["stopped_because"] is None
            continue
        assert plan["stopped_because"] in budget.STOP_REASONS
        assert plan["stopped_note"]


def test_the_surplus_walk_runs_or_says_why_it_did_not():
    """Either the tier gets used, or the plan names what stopped it. Never neither."""
    for plan in every_plan(view()):
        moved = any(role.get("upgraded_from") for role in plan["roles"].values())
        assert moved or plan["stopped_because"], f"{plan['name']} neither spent nor explained"


def test_a_role_you_iterate_with_never_outlasts_its_patience():
    """The architect may be slow — a plan is made once, deliberately. The loop roles may not."""
    for plan in every_plan(view()):
        ceilings = budget.PATIENCE[plan["patience"]]
        for name in ("worker", "scout"):
            pick = plan["roles"][name]["pick"]
            minutes = budget.loop_minutes(pick) if pick else None
            if minutes is not None and ceilings[name] is not None:
                assert minutes <= ceilings[name], f"{name} takes {minutes} min at {plan['patience']}"


def test_an_unmeasured_model_is_not_treated_as_slow():
    """Absence of a measurement decides nothing — the same rule the drift veto learned."""
    unmeasured = {"key": "mystery", "effort": "max", "score": 60.0, "cost_uusd": 1_000_000}
    assert budget.quick_enough(unmeasured, 3)
    assert budget.quick_enough({**unmeasured, "speed": {"task_minutes": 2}}, 3)
    assert not budget.quick_enough({**unmeasured, "speed": {"task_minutes": 8}}, 3)
    assert budget.quick_enough({**unmeasured, "speed": {"task_minutes": 40}}, None)


def test_no_plan_ever_passes_the_safety_cap():
    """The month is a model, not a meter — leave room for a heavier one."""
    for plan in every_plan(view()):
        assert plan["month_credits"] <= plan["credits"] * budget.MAX_UTILISATION + 1


def test_surplus_reaches_planning_before_the_mechanical_role():
    """Cheapest-point buying once put an Opus on the scout while the worker was still light.

    Built rather than observed: every role is given the same affordable ladder and enough
    budget for exactly one step, so which role takes it is the rule under test and nothing
    else.
    """
    # Sized so the opening shares cannot reach the top rung but the tier's surplus can —
    # otherwise every role starts at the top and there is nothing to order.
    rows = [
        aa_row(f"rung{index}", "max", score, cost, minutes=0.5)
        for index, (score, cost) in enumerate([(50.0, 1_000_000), (55.0, 3_000_000), (60.0, 30_000_000)])
    ]
    settings = Settings(tiers=[{"id": "one_step", "name": "One step", "credits": 100_000}])
    plan = recommend.build(
        rows, [], sold(*(row["model_key"] for row in rows)), settings, [], credit_usd=0.01
    )["plans"]["one_step"][budget.DEFAULT_PATIENCE]
    roles = plan["roles"]
    assert roles["architect"]["upgraded_from"], "the surplus skipped planning"
    assert not roles["scout"]["upgraded_from"], "the mechanical role was served first"


def test_spending_the_surplus_keeps_three_distinct_roles():
    for plan in every_plan(view()):
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


def test_a_scout_never_opens_dearer_than_its_worker():
    """At Heavy/Fast the scout's quick frontier ended on Opus 5.5 · Low (55 credits) while the
    worker's ended on GPT-6 Sol · Extra High (53): the worker had skipped it for a cheaper,
    better variant. The opening picks keep the stack's shape too, not only the surplus walk."""
    rows = [
        aa_row("a", "medium", 39.8, 248_000, minutes=1.0),
        aa_row("b", "low", 42.3, 551_000, minutes=1.3),    # quick enough for the scout
        aa_row("c", "xhigh", 44.1, 532_000, minutes=2.5),  # too slow for it, fine for the worker
    ]
    payload = recommend.build(rows, [], sold("a", "b", "c"), Settings(), [], credit_usd=0.01)
    for by_patience in payload["plans"].values():
        roles = by_patience["fast"]["roles"]
        assert roles["worker"]["pick"]["key"] == "c"
        assert roles["scout"]["pick"]["cost_uusd"] <= roles["worker"]["pick"]["cost_uusd"]
        assert roles["scout"]["pick"]["key"] == "a"
