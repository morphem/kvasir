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
        assert set(plan["roles"]) == {"architect", "worker", "scout", "subagent"}
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
        assert plan["headroom_credits"] >= 0


def test_a_tier_too_small_for_anything_says_so():
    payload = view(tiers=[{"id": "sliver", "name": "Sliver", "credits": 10}])
    roles = payload["plans"]["sliver"][budget.DEFAULT_PATIENCE]["roles"]
    base = [roles[name] for name in ("architect", "worker", "scout")]
    assert all(role["pick"] is None for role in base)
    assert all("Nothing on the board" in role["why"] for role in base)


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






def test_a_role_you_iterate_with_never_outlasts_its_patience():
    """The architect may be slow — a plan is made once, deliberately. The loop roles may not."""
    for plan in every_plan(view()):
        ceilings = budget.PATIENCE[plan["patience"]]
        for name in ("worker", "scout"):
            pick = plan["roles"][name]["pick"]
            minutes = budget.loop_minutes(pick) if pick else None
            if minutes is not None and ceilings[name] is not None:
                assert minutes <= ceilings[name], f"{name} takes {minutes} min at {plan['patience']}"


def test_an_untimed_variant_cannot_promise_a_ceiling():
    """A ceiling is a promise about time; only Any pace, which makes none, lets it compete."""
    untimed = {"key": "mystery", "effort": "max", "score": 60.0, "cost_uusd": 1_000_000}
    assert not budget.quick_enough(untimed, 3)
    assert budget.quick_enough(untimed, None)
    assert budget.quick_enough({**untimed, "speed": {"task_minutes": 2}}, 3)
    assert not budget.quick_enough({**untimed, "speed": {"task_minutes": 8}}, 3)
    assert budget.quick_enough({**untimed, "speed": {"task_minutes": 40}}, None)


def test_an_untimed_model_takes_no_loop_seat_under_a_ceiling_and_is_named():
    """Gemini 4 Argon · High, scored and priced but never timed, once took both the Fast
    worker and the Fast scout. Under a ceiling it now takes neither, and the worker's card
    says why (the scout's names only a cheaper variant it passed over)."""
    rows = [
        aa_row("planner", "max", 60.0, 2_000_000, minutes=10),
        aa_row("argon", "high", 55.0, 400_000),
        aa_row("quick", "medium", 48.0, 200_000, minutes=1),
    ]
    view = recommend.build(rows, [], sold("planner", "argon", "quick"), Settings(), [])
    fast = view["plans"]["heavy"]["fast"]["roles"]
    assert fast["worker"]["pick"]["key"] == fast["scout"]["pick"]["key"] == "quick"
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


def test_the_scout_is_the_cheapest_variant_over_the_bar():
    """Not the best the tier buys: the cheapest that reaches SCOUT_BAR of the leader."""
    payload = view()
    priced = [c for c in payload["candidates"] if c["priced"] and c["available"]]
    leader = max(c["score"] for c in priced)
    for tier_id, by_patience in payload["plans"].items():
        for patience_id, plan in by_patience.items():
            scout = plan["roles"]["scout"]
            bar = scout["bar"]
            assert bar["share"] == budget.SCOUT_BAR
            assert bar["score"] == round(leader * budget.SCOUT_BAR, 1)
            if scout["under_bar"]:
                assert "Nothing at 75%" in scout["why"]
                continue
            pick = scout["pick"]
            assert pick["score"] >= bar["score"]
            ceiling = budget.PATIENCE[patience_id]["scout"]
            cheaper = [
                c for c in priced
                if c["score"] >= bar["score"]
                and c["cost_uusd"] < pick["cost_uusd"]
                and budget.quick_enough(c, ceiling)
            ]
            assert not cheaper, f"{tier_id}/{patience_id}: {cheaper[0]['label']} was cheaper"




def test_a_cheaper_variant_too_slow_for_the_scout_is_named():
    rows = [
        aa_row("top", "max", 60.0, 5_000_000, minutes=2.0),
        aa_row("slowcheap", "max", 46.0, 100_000, minutes=6.0),  # over the bar, too slow
        aa_row("quick", "low", 47.0, 200_000, minutes=1.0),
        aa_row("weak", "low", 30.0, 10_000, minutes=0.5),  # quick and cheap, under the bar
    ]
    payload = recommend.build(rows, [], sold(*(r["model_key"] for r in rows)), Settings(), [], credit_usd=0.01)
    balanced = payload["plans"]["heavy"]["balanced"]["roles"]["scout"]
    assert balanced["pick"]["key"] == "quick"
    assert balanced["speed_blocked"]["label"] == "Slowcheap · Max"
    anything = payload["plans"]["heavy"]["any"]["roles"]["scout"]
    assert anything["pick"]["key"] == "slowcheap"


def test_a_scout_with_nothing_over_the_bar_takes_the_best_that_fits_and_says_so():
    rows = [
        aa_row("top", "max", 60.0, 5_000_000, minutes=2.0),
        aa_row("weak", "low", 30.0, 10_000, minutes=0.5),
        aa_row("weaker", "low", 25.0, 5_000, minutes=0.5),
    ]
    payload = recommend.build(rows, [], sold(*(r["model_key"] for r in rows)), Settings(), [], credit_usd=0.01)
    scout = payload["plans"]["heavy"]["fast"]["roles"]["scout"]
    assert scout["under_bar"] is True
    assert scout["pick"]["key"] == "weak"
    assert "Nothing at 75% of the leader (45.0)" in scout["why"]


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


def test_the_subagent_is_the_cheapest_good_enough_on_the_agentic_evaluations():
    """Chosen on AutomationBench and Terminal-Bench, not the Intelligence Index."""
    rows = [
        agentic_row("smart", "max", 60.0, 5_000_000, 70.0, 60.0, minutes=2),   # leader: 65
        agentic_row("doer", "low", 40.0, 200_000, 60.0, 40.0),                 # 50: over 48.75
        agentic_row("clever", "low", 50.0, 150_000, 30.0, 20.0),               # higher index, weak agent
        agentic_row("slowdoer", "low", 40.0, 100_000, 62.0, 42.0, minutes=9),  # over the bar, too slow
    ]
    view = recommend.build(rows, [], sold(*(r["model_key"] for r in rows)), Settings(), [], credit_usd=0.01)
    sub = view["plans"]["heavy"]["balanced"]["roles"]["subagent"]
    assert sub["pick"]["key"] == "doer"
    assert sub["agentic_score"] == 50.0
    assert sub["speed_blocked"]["label"].startswith("Slowdoer")
    assert view["plans"]["heavy"]["any"]["roles"]["subagent"]["pick"]["key"] == "slowdoer"


def test_a_board_without_agentic_scores_says_so_instead_of_picking():
    payload = view()
    for plan in every_plan(payload):
        sub = plan["roles"]["subagent"]
        if sub["pick"] is None:
            assert "agentic" in sub["why"]
