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

# An allowance is not a saving. Credits left unspent at the end of the month buy nothing —
# they are pooled back at the billing entity — so once the economical picks are in, the plan
# keeps climbing until it uses this much of the tier. Stopping at 27% of a 100k allowance was
# not thrift, it was leaving capability on the table.
TARGET_UTILISATION = 0.80
# The month is a model, not a meter. Never plan past this, so a heavier month than assumed
# does not run the tier dry.
MAX_UTILISATION = 0.90

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


def steady(candidate: dict) -> bool:
    """Measured, and measured as holding.

    Not the same as "not drifting": a model absent from AI Stupid Level is not drifting
    either, and it must not win a veto on that basis. Otherwise the models nobody measures
    beat every model that is measured, purely by having no record — which is how an
    unmeasured model took all three roles here.
    """
    return bool(candidate.get("drift")) and not drifting(candidate)


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


def _avoid_drift(pick: dict, affordable: list[dict], trusted: bool = True):
    """Trade a sliding model for a steady one, as long as the trade is nearly free.

    Only a model with its own evidence of holding steady can take the slot, and only while
    the drift signal itself is fresh — a frozen reading keeps vetoing the same model for as
    long as the source stays down.
    """
    if not trusted or not drifting(pick):
        return pick, None
    for other in sorted(affordable, key=lambda c: -c["score"]):
        if other is pick or not steady(other):
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
    upgraded_from: str | None = None,
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
    if upgraded_from:
        base += (
            f" Bought up from {upgraded_from} with the tier's unused credits: this plan aims to "
            f"use {int(TARGET_UTILISATION * 100)}% of the allowance rather than hand it back."
        )
    if drift_replaced:
        base += (
            f" Not {drift_replaced['label']}: that one is sliding on AI Stupid Level, and the "
            "swap costs almost nothing."
        )
    return base


def _best_upgrade(pick: dict, pool: list[dict], credit_usd: float, allowed=None):
    """The cheapest quality on offer above the current pick, in credits per point.

    Same discipline as the value ladder, only the question is inverted: not "is this step
    worth taking" but "if we are going to spend the surplus, where does a point cost least".

    `allowed` filters the rungs this role may take at all. It belongs here rather than in the
    caller: rejecting only the single cheapest rung and giving up on the role left a tier at
    61% with three legal upgrades still on the board.
    """
    current = credits_for(pick["cost_uusd"], credit_usd)
    best = None
    for other in pool:
        gain = other["score"] - pick["score"]
        if gain <= 0:
            continue
        if allowed and not allowed(other):
            continue
        extra = credits_for(other["cost_uusd"], credit_usd) - current
        per_point = extra / gain
        if best is None or per_point < best[1]:
            best = (other, per_point, extra)
    return best


ROLE_ORDER = {"architect": 0, "worker": 1, "scout": 2}


def _keeps_roles_apart(state: dict, role: str, candidate: dict) -> bool:
    """Would this upgrade still leave three distinguishable roles?

    Surplus is worth spending, but not on collapsing the board: three cards naming one model
    tell you nothing, and an Opus running a file rename is money and wall-clock time spent
    where neither buys anything. So a role may not climb onto another role's model, and the
    ranking architect >= worker >= scout has to survive the step.
    """
    for other_role, other in state.items():
        if other_role == role or not other["pick"]:
            continue
        pick = other["pick"]
        if candidate["key"] == pick["key"] and candidate["effort"] == pick["effort"]:
            return False
        if ROLE_ORDER[role] < ROLE_ORDER[other_role] and candidate["score"] < pick["score"]:
            return False
        if ROLE_ORDER[role] > ROLE_ORDER[other_role] and candidate["score"] > pick["score"]:
            return False
    return True


def _spend_the_tier(state: dict, tier_credits: int, credit_usd: float, drift_trusted: bool) -> list[dict]:
    """Climb from the economical picks until the tier is properly used.

    Role shares decide the opening position; from there the only ceiling is the tier itself,
    because a share is an allocation and the allowance is what actually runs out.

    The surplus is spent **in role order** — architect, then worker, then scout — rather than
    wherever a point is cheapest. Cheapest-point buying put an Opus on the mechanical role
    while the worker was still on a light model: quality converts into value at the top of
    the stack, and the scout should only get expensive when there is genuinely nothing else
    left to do with the money.
    """
    if not tier_credits:
        return []
    target = tier_credits * TARGET_UTILISATION
    cap = tier_credits * MAX_UTILISATION
    steps: list[dict] = []

    def projected() -> float:
        return sum(
            credits_for(slot["pick"]["cost_uusd"], credit_usd) * slot["billable_tasks"]
            for slot in state.values()
            if slot["pick"]
        )

    for role in ("architect", "worker", "scout"):
        slot = state[role]
        for _ in range(12):  # the board is small; this is a guard, not a budget
            spent = projected()
            if spent >= target or not slot["pick"]:
                break
            headroom = cap - spent
            found = _best_upgrade(
                slot["pick"],
                slot["surplus_pool"],
                credit_usd,
                allowed=lambda candidate, slot=slot, headroom=headroom, role=role: (
                    _keeps_roles_apart(state, role, candidate)
                    and (
                        credits_for(candidate["cost_uusd"], credit_usd)
                        - credits_for(slot["pick"]["cost_uusd"], credit_usd)
                    )
                    * slot["billable_tasks"]
                    <= headroom
                ),
            )
            if not found:
                break
            chosen = found[0]
            upgraded, _ = _avoid_drift(chosen, slot["surplus_pool"], drift_trusted)
            previous = slot["pick"]
            if upgraded["key"] == previous["key"] and upgraded["effort"] == previous["effort"]:
                break  # the drift veto sent us back where we started
            slot["pick"] = upgraded
            steps.append({"role": role, "from": previous["label"], "to": upgraded["label"]})
    return steps


def plan_for_tier(
    tier: dict,
    candidates: list[dict],
    frontier: list[dict],
    credit_usd: float,
    reference: dict,
    drift_trusted: bool = True,
) -> dict:
    """Fill the three roles under one tier's monthly credit budget."""
    monthly = tasks_per_month()
    roles = {}
    total_credits = 0.0
    board_best = max(candidates, key=lambda c: (c["score"], -c["cost_uusd"]), default=None)

    # Phase one: what each role would take on economics alone, inside its own share.
    state: dict[str, dict] = {}
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
            pick, drift_replaced = _avoid_drift(pick, pool, drift_trusted)
        else:
            drift_replaced = None
        state[role] = {
            "pick": pick,
            "baseline": pick,
            "drift_replaced": drift_replaced,
            "pool": pool,
            # Spending the surplus is bounded by the tier, not by the opening allocation.
            "surplus_pool": candidates if role == "architect" else frontier,
            "share_credits": share_credits,
            "billable_tasks": billable_tasks,
            "per_task": per_task,
        }

    # Phase two: an unused credit buys nothing, so climb until the tier is properly used.
    upgrades = _spend_the_tier(state, tier["credits"], credit_usd, drift_trusted)
    upgraded_roles = {step["role"]: step["from"] for step in upgrades}

    for role in ("architect", "worker", "scout"):
        slot = state[role]
        pick, drift_replaced = slot["pick"], slot["drift_replaced"]
        share_credits, billable_tasks, per_task = (
            slot["share_credits"], slot["billable_tasks"], slot["per_task"]
        )
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

        # What the budget actually costs this role, and only where that question makes
        # sense. The architect's rule is "buy the best you can afford", so naming the model
        # it could not afford is informative. The worker and the scout stop climbing for
        # economic reasons, not budget ones — telling them about a model they deliberately
        # did not want would be noise.
        out_of_reach = None
        if role == "architect" and board_best is not None and board_best["key"] != pick["key"]:
            best_price = credits_for(board_best["cost_uusd"], credit_usd)
            # The ceiling that matters is what the plan could still pay after the other roles
            # are served — not the opening share, which the surplus walk is allowed to pass.
            others = sum(
                credits_for(other["pick"]["cost_uusd"], credit_usd) * other["billable_tasks"]
                for name, other in state.items()
                if name != role and other["pick"]
            )
            reachable = (tier["credits"] * MAX_UTILISATION - others) / billable_tasks
            if best_price is not None and best_price > reachable:
                out_of_reach = {
                    "label": board_best["label"],
                    "score": board_best["score"],
                    "per_task_credits": round(best_price),
                    "ceiling_credits": round(max(reachable, 0)),
                }
        roles[role] = {
            "pick": pick,
            "why": _why(
                role, pick, per_task, per_task_credits, monthly[role], drift_replaced,
                upgraded_roles.get(role),
            ),
            "upgraded_from": upgraded_roles.get(role),
            "drift_replaced": drift_replaced["label"] if drift_replaced else None,
            "out_of_reach": out_of_reach,
            "share_credits": round(share_credits),
            "per_task_budget_credits": round(per_task),
            "per_task_credits": round(per_task_credits, 1),
            "tasks_per_month": monthly[role],
            "month_credits": round(month_credits),
            "month_usd": round(month_credits * credit_usd, 2),
            "share_used_pct": round(100 * month_credits / share_credits, 1) if share_credits else None,
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


def plans(
    tiers: list[dict],
    candidates: list[dict],
    frontier: list[dict],
    credit_usd: float,
    reference: dict,
    drift_trusted: bool = True,
) -> dict:
    return {
        tier["id"]: plan_for_tier(tier, candidates, frontier, credit_usd, reference, drift_trusted)
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
        "target_utilisation": TARGET_UTILISATION,
        "max_utilisation": MAX_UTILISATION,
    }
