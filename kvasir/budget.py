"""AI-credit tiers: what a month of ordinary work costs, and what each tier can run.

GitHub bills Copilot in AI credits, and its own docs put the rate in one sentence:
"the total is converted into AI credits, where 1 AI credit = $0.01 USD". The collector reads
that sentence off the pricing page rather than trusting a constant here, so if GitHub ever
changes the rate the page notices instead of quietly lying.

That single fact is what makes CursorBench's dollar-per-task usable as a credit budget:
one task at $2.31 is 231 credits, and a tier is just a number of credits per month.

The month is modelled, not measured — nobody has a per-task meter — so every assumption
below is a named constant that the page prints next to the result. The profile is the
*average* engineer: one project or integration at a time, no parallel sessions.
"""

from __future__ import annotations

# What "a month of work" means here. Deliberately conservative on task count and honest
# about the fact that not every interaction looks like a benchmark task.
WORKING_DAYS = 21
TASKS_PER_DAY = 6
ROLE_MIX = {"architect": 0.10, "worker": 0.50, "scout": 0.40}

# Chat questions, follow-ups and the occasional retry are billed too and do not look like a
# benchmark task. This scales the whole estimate rather than pretending to model them.
OVERHEAD = 1.15

# How much of the monthly budget each role may claim. Planning is where quality pays, so it
# gets the largest slice despite being the smallest slice of tasks.
BUDGET_SHARES = {"architect": 0.35, "worker": 0.45, "scout": 0.20}

# Upgrade discipline, in dollars per percentage point of CursorBench score. The worker walks
# up the ladder while the next step is at most "fair"; the scout only takes bargains, because
# on mechanical work the extra quality is not worth anything; the architect ignores both and
# simply buys the best its share can afford.
FAIR_USD_PER_PP = 0.75
BARGAIN_USD_PER_PP = 0.15

CREDIT_USD_FALLBACK = 0.01

# A model whose AI Stupid Level score is sliding, or already flagged, loses a role to a
# comparable model that is holding steady — at most this far behind on score.
DRIFT_DOWN_STATUSES = {"warning", "critical"}
DRIFT_MAX_SCORE_LOSS_PP = 1.5


def drifting(candidate: dict) -> bool:
    drift = candidate.get("drift")
    if not drift:
        return False
    return drift.get("trend") == "down" or drift.get("status") in DRIFT_DOWN_STATUSES


def tasks_per_month() -> dict[str, float]:
    total = WORKING_DAYS * TASKS_PER_DAY
    return {role: round(total * share, 1) for role, share in ROLE_MIX.items()}


def credits_for(cost_uusd: int | None, credit_usd: float) -> float | None:
    """A task's price in AI credits. 1 credit = $0.01, so $2.31 per task is 231 credits."""
    if cost_uusd is None or not credit_usd:
        return None
    return (cost_uusd / 1_000_000) / credit_usd


def _fits(candidate: dict, per_task_credits: float, credit_usd: float) -> bool:
    price = credits_for(candidate["cost_uusd"], credit_usd)
    return price is not None and price <= per_task_credits


def _walk_ladder(frontier: list[dict], per_task_credits: float, credit_usd: float, max_usd_per_pp: float):
    """Climb the cost/quality frontier while each step is affordable and worth its price.

    Starting at the cheapest model, take the next step only if the monthly share still
    covers it and the extra quality costs no more than `max_usd_per_pp` per point. This is
    the same discipline the value ladder on the page shows, applied to a budget.
    """
    affordable = [c for c in frontier if _fits(c, per_task_credits, credit_usd)]
    if not affordable:
        return None
    pick = affordable[0]
    for nxt in affordable[1:]:
        gain = nxt["score"] - pick["score"]
        if gain <= 0:
            continue
        step_usd = (nxt["cost_uusd"] - pick["cost_uusd"]) / 1_000_000
        if step_usd / gain <= max_usd_per_pp:
            pick = nxt
    return pick


def _avoid_drift(pick: dict, affordable: list[dict]):
    """Trade a sliding model for a steady one, as long as the trade is nearly free."""
    if not drifting(pick):
        return pick, None
    for other in sorted(affordable, key=lambda c: -c["score"]):
        if other is pick or drifting(other):
            continue
        if other["score"] >= pick["score"] - DRIFT_MAX_SCORE_LOSS_PP:
            return other, pick
    return pick, None


def _best_affordable(candidates: list[dict], per_task_credits: float, credit_usd: float):
    affordable = [c for c in candidates if _fits(c, per_task_credits, credit_usd)]
    if not affordable:
        return None
    return max(affordable, key=lambda c: (c["score"], -c["cost_uusd"]))


def _why(
    role: str,
    pick: dict,
    per_task_budget: float,
    per_task: float,
    tasks: float,
    drift_replaced: dict | None = None,
) -> str:
    """Why this model, in this role, at this tier — in the terms the budget is managed in."""
    price = f"{per_task:.0f} credits a task"
    if role == "architect":
        base = (
            f"Best model this tier's planning share affords: {price} against a "
            f"{per_task_budget:.0f}-credit ceiling, {tasks:g} planning tasks a month."
        )
    elif role == "worker":
        base = (
            f"Climbs the value ladder while each step costs at most ${FAIR_USD_PER_PP:.2f} per "
            f"point and stays under {per_task_budget:.0f} credits a task. Lands at {price}."
        )
    else:
        base = (
            f"Takes only bargain upgrades (at most ${BARGAIN_USD_PER_PP:.2f} per point) — mechanical "
            f"work does not repay more. {price}."
        )
    if drift_replaced:
        base += (
            f" Not {drift_replaced['label']}: that one is sliding on AI Stupid Level, and the "
            "swap costs almost nothing."
        )
    return base


def plan_for_tier(
    tier: dict, candidates: list[dict], frontier: list[dict], credit_usd: float, reference: dict
) -> dict:
    """Fill the three roles under one tier's monthly credit budget."""
    monthly = tasks_per_month()
    roles = {}
    total_credits = 0.0

    for role in ("architect", "worker", "scout"):
        share_credits = tier["credits"] * BUDGET_SHARES[role]
        billable_tasks = monthly[role] * OVERHEAD
        per_task = share_credits / billable_tasks if billable_tasks else 0.0

        if role == "architect":
            pick = _best_affordable(candidates, per_task, credit_usd)
            pool = [c for c in candidates if _fits(c, per_task, credit_usd)]
        else:
            ceiling = FAIR_USD_PER_PP if role == "worker" else BARGAIN_USD_PER_PP
            pick = _walk_ladder(frontier, per_task, credit_usd, ceiling)
            pool = [c for c in frontier if _fits(c, per_task, credit_usd)]
        if pick is not None:
            # The budget decides what is affordable; drift still decides what is sane.
            pick, drift_replaced = _avoid_drift(pick, pool)
        else:
            drift_replaced = None
        if pick is None:
            # Nothing on the board fits this share — say so instead of inventing a pick.
            roles[role] = {
                "pick": None,
                "per_task_budget_credits": round(per_task),
                "share_credits": round(share_credits),
                "why": (
                    f"Nothing on the board runs {monthly[role]:g} tasks a month inside this "
                    f"tier's {int(BUDGET_SHARES[role] * 100)}% share — that is "
                    f"{round(per_task)} credits a task."
                ),
            }
            continue

        per_task_credits = credits_for(pick["cost_uusd"], credit_usd)
        month_credits = per_task_credits * billable_tasks
        total_credits += month_credits
        best = (reference.get(role) or {}).get("pick")
        roles[role] = {
            "pick": pick,
            "why": _why(role, pick, per_task, per_task_credits, monthly[role], drift_replaced),
            "drift_replaced": drift_replaced["label"] if drift_replaced else None,
            "share_credits": round(share_credits),
            "per_task_budget_credits": round(per_task),
            "per_task_credits": round(per_task_credits, 1),
            "tasks_per_month": monthly[role],
            "month_credits": round(month_credits),
            "month_usd": round(month_credits * credit_usd, 2),
            "share_used_pct": round(100 * month_credits / share_credits, 1) if share_credits else None,
            "downgraded_from": None
            if not best or (best["key"] == pick["key"] and best["effort"] == pick["effort"])
            else best["label"],
        }

    # At a tight budget the worker and the scout collapse onto the same model. That is an
    # answer, not a bug, so it gets said once instead of dressed up as two roles.
    for lower, upper in (("scout", "worker"), ("worker", "architect")):
        low, high = roles[lower].get("pick"), roles[upper].get("pick")
        if low and high and low["key"] == high["key"] and low["effort"] == high["effort"]:
            roles[lower]["same_as"] = upper

    # What the unconstrained shortlist would cost here — the number that says whether the
    # tier, and not the benchmark, is the thing deciding your models.
    reference_credits = 0.0
    for role, verdict in reference.items():
        pick = verdict.get("pick")
        price = credits_for(pick["cost_uusd"], credit_usd) if pick else None
        if price is not None:
            reference_credits += price * monthly[role] * OVERHEAD

    return {
        **tier,
        "usd": round(tier["credits"] * credit_usd, 2),
        "roles": roles,
        "month_credits": round(total_credits),
        "month_usd": round(total_credits * credit_usd, 2),
        "used_pct": round(100 * total_credits / tier["credits"], 1) if tier["credits"] else None,
        "headroom_credits": round(tier["credits"] - total_credits),
        "reference_credits": round(reference_credits),
        "reference_used_pct": round(100 * reference_credits / tier["credits"], 1) if tier["credits"] else None,
        "reference_fits": reference_credits <= tier["credits"],
    }


def plans(tiers: list[dict], candidates: list[dict], frontier: list[dict], credit_usd: float, reference: dict) -> dict:
    return {
        tier["id"]: plan_for_tier(tier, candidates, frontier, credit_usd, reference)
        for tier in tiers
    }


def assumptions(credit_usd: float) -> dict:
    """Everything the estimate rests on, so the page can print it."""
    monthly = tasks_per_month()
    return {
        "credit_usd": credit_usd,
        "working_days": WORKING_DAYS,
        "tasks_per_day": TASKS_PER_DAY,
        "tasks_per_month": round(sum(monthly.values()), 1),
        "role_mix": ROLE_MIX,
        "tasks_by_role": monthly,
        "overhead": OVERHEAD,
        "budget_shares": BUDGET_SHARES,
        "fair_usd_per_pp": FAIR_USD_PER_PP,
        "bargain_usd_per_pp": BARGAIN_USD_PER_PP,
    }
