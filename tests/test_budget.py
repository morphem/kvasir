"""The credit layer: a month of work, priced in AI credits, against a tier.

These tests pin the arithmetic and the discipline, not the specific models — the models are
whatever the live data says this week.
"""

from conftest import fixture

from kvasir import budget, recommend
from kvasir.collectors import copilot, cursorbench, stupidlevel
from kvasir.config import Settings


def view(tiers=None):
    cb, _ = cursorbench.parse(fixture("cursorbench.html"))
    ai, _ = stupidlevel.parse(fixture("stupidlevel-scores.json"))
    cp, cp_meta = copilot.parse(fixture("copilot-models-and-pricing.html"))
    settings = Settings()
    if tiers:
        settings = Settings(tiers=tiers)
    return recommend.build(
        cb, ai, cp, settings, settings.hidden_models, credit_usd=cp_meta.get("credit_usd")
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
    assert basic["roles"]["architect"]["downgraded_from"]  # the budget, not the benchmark, decided
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


def test_the_scout_refuses_to_pay_for_quality_it_cannot_use():
    """Even with a huge budget the mechanical role stays on bargain upgrades."""
    payload = view(tiers=[{"id": "silly", "name": "Silly", "credits": 5_000_000}])
    plan = payload["plans"]["silly"]
    scout = plan["roles"]["scout"]["pick"]
    architect = plan["roles"]["architect"]["pick"]
    assert scout["cost_uusd"] < architect["cost_uusd"]
    assert plan["used_pct"] < 5  # an unlimited budget is not an invitation to spend it


def test_assumptions_are_published_with_the_answer():
    payload = view()
    assumptions = payload["assumptions"]
    assert assumptions["tasks_per_month"] == budget.WORKING_DAYS * budget.TASKS_PER_DAY
    assert sum(assumptions["role_mix"].values()) == 1.0
    assert sum(assumptions["budget_shares"].values()) == 1.0
    assert assumptions["overhead"] >= 1.0
