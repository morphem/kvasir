"""AI-credit tiers: what a month of ordinary work costs, and what each tier can run.

GitHub bills Copilot in AI credits, and its own docs put the rate in one sentence:
"the total is converted into AI credits, where 1 AI credit = $0.01 USD". The collector reads
that sentence off the pricing page rather than trusting a constant here, so if GitHub ever
changes the rate the page notices instead of quietly lying.

That single fact is what makes Artificial Analysis's dollar-per-task usable as a credit
budget: one Intelligence Index task at $2.31 is 231 credits, and a tier is just a number of
credits per month.

The month is modelled, not measured — nobody has a per-task meter — so every assumption
below is a named constant that the page prints next to the result.

Since 2026-11-19 a tier is read as a daily allowance to be used up, not a ceiling to stay
under (owner's call): credits left at the end of the month buy nothing, and more agent runs
are more work done. The picks are sized on a *base day* — a few tasks in a fixed mix, the
smallest day worth planning for — so a small tier still gets models it can actually run. What
the day's allowance buys beyond that base day is the tier's throughput: so many more worker
tasks, subagent runs or architect plans. Patience caps how good a loop model may be, so past
a point money cannot buy a better one — only more of them, in parallel.
"""

from __future__ import annotations

# The base day the picks are sized on: the smallest day worth planning for, not a forecast of
# a real one — everything the allowance buys past it is reported as throughput. Twenty working
# days is the owner's figure (2026-11-19): 200K credits is 10K a day.
WORKING_DAYS = 20
TASKS_PER_DAY = 6
ROLE_MIX = {"architect": 0.10, "worker": 0.90}

# Chat questions, follow-ups and the occasional retry are billed too and do not look like a
# benchmark task. This scales the whole estimate rather than pretending to model them.
OVERHEAD = 1.15

# How much of the base day each role may claim. Planning is where quality pays, so it gets a
# third of the money for a tenth of the tasks. Until 2026-11-19 a third role, the scout, held
# 40% of the tasks and 20% of the money for mechanical work; on the November board it was the
# worker's own model at a lower effort in six of nine plans, so its tasks and its share went
# to the worker (owner's call). A quicker effort of the worker's model is named on its card.
BUDGET_SHARES = {"architect": 0.35, "worker": 0.65}

# Upgrade discipline, in dollars per point. The worker walks up the Intelligence Index ladder,
# and the subagent up the agentic one, while the next step is at most "fair"; the architect
# ignores it and simply buys the best its share can afford. A step up to "bargain" or cheaper
# is how the page grades the gap between two roles.
FAIR_USD_PER_PP = 0.75
BARGAIN_USD_PER_PP = 0.15

# The subagent: the model the architect hands a sub-task to and does not watch. Chosen on the
# agentic evaluations, not the Intelligence Index — AutomationBench-AA (multi-step work across
# tools and APIs) and Terminal-Bench 4.0 (agentic coding in a terminal), averaged. It starts at
# the cheapest variant within the worker's patience that reaches this share of the agentic
# leader, and climbs while an agentic point costs at most FAIR_USD_PER_PP. A share of the
# leader, not a score: the evaluations are re-based and the market climbs. Three quarters, set
# with the role on 2026-11-19 before looking at who it seats. Until 2026-11-19 (v2.12) it took
# the cheapest over the bar and stopped: that seated GPT-6.1 Sol · Medium (55 points, 36
# credits) over GPT-6.2 Sol · Medium (63 points, 41 credits) — the scout's rule, wrong for the
# role the spare allowance is spent on.
SUBAGENT_BAR = 0.75

# A quicker way to run the worker's model, named on its card: the same model at an effort
# that finishes a task in at most this share of the worker's time. It replaces the scout as a
# role — an effort dial, not a second model to switch to.
QUICK_SHARE = 0.5

# Patience: the longest a loop role may take over one task, in minutes. The worker is the role
# you iterate with — prompt, read, correct, prompt again — and the subagent is the loop the
# architect waits on, so the length of one loop is the length of the job: a model that takes
# eight minutes per task makes a ten-round session last an afternoon. The architect is exempt:
# a plan is made once, deliberately, and it is worth waiting for.
#
# The clock is Artificial Analysis's time per Intelligence Index task — decode time, reasoning
# included — measured in the same runs as the score and the cost, per effort. Reasoning effort
# *is* the time: Opus 5.5 takes 1.3 minutes a task at low and 7.5 at extra high. It replaced two
# earlier clocks: a tokens-per-second floor, which barred whole models once the source timed
# everything, and the wait to the first answer, which says when a loop starts, not how long it
# lasts. The page switches between these like it switches tiers.
#
# A ceiling is a promise about time, so a loop role under one needs a time. A variant nobody
# timed is held to a lower effort of the same model when one was timed (see
# recommend._task_floor); with no time at all it cannot take a loop seat while a ceiling is set,
# and the card names it. At Any pace there is no ceiling and it competes. Until 2026-10-14 an
# untimed variant passed ("absence of evidence decides nothing"); then Gemini 4 Argon · High,
# scored and priced but never timed, took the Fast worker's seat at 199 credits a task, on a
# time nobody measured.
PATIENCE = {
    "fast": {"label": "Fast", "worker": 3.0},
    "balanced": {"label": "Balanced", "worker": 6.0},
    "any": {"label": "Any pace", "worker": None},
}
DEFAULT_PATIENCE = "balanced"

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


def loop_minutes(candidate: dict) -> float | None:
    """Minutes one task takes on this exact variant — or None if nobody timed it."""
    speed = candidate.get("speed")
    return speed.get("task_minutes") if speed else None


def quick_enough(candidate: dict, ceiling: float | None) -> bool:
    if ceiling is None:
        return True
    minutes = loop_minutes(candidate)
    return minutes is not None and minutes <= ceiling


def frontier(candidates: list[dict], score=lambda c: c["score"]) -> list[dict]:
    """The cost/quality frontier: models nothing else beats on price and score at once."""
    ordered = sorted(candidates, key=lambda c: (c["cost_uusd"], -score(c)))
    out: list[dict] = []
    best = float("-inf")
    for candidate in ordered:
        if score(candidate) > best:
            out.append(candidate)
            best = score(candidate)
    return out


def steady(candidate: dict) -> bool:
    """Measured, and measured as holding.

    Not the same as "not drifting": a model absent from AI Stupid Level is not drifting
    either, and it must not win a veto on that basis. Otherwise the models nobody measures
    beat every model that is measured, purely by having no record — which is how an
    unmeasured model took every role here.
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


def _climb(rungs: list[dict], max_usd_per_pp: float, score=lambda c: c["score"]):
    """From the first rung, take each next one whose extra points cost at most the ceiling."""
    if not rungs:
        return None
    pick = rungs[0]
    for nxt in rungs[1:]:
        gain = score(nxt) - score(pick)
        if gain <= 0:
            continue
        step_usd = (nxt["cost_uusd"] - pick["cost_uusd"]) / 1_000_000
        if step_usd / gain <= max_usd_per_pp:
            pick = nxt
    return pick


def _walk_ladder(rungs: list[dict], per_task_credits: float, credit_usd: float, max_usd_per_pp: float):
    """Climb the cost/quality frontier while each step is affordable and worth its price.

    Starting at the cheapest model, take the next step only if the share still covers it and
    the extra quality costs no more than `max_usd_per_pp` per point. This is the same
    discipline the value ladder on the page shows, applied to a budget.
    """
    return _climb([c for c in rungs if _fits(c, per_task_credits, credit_usd)], max_usd_per_pp)


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


def _cheapest(candidates: list[dict]):
    return min(candidates, key=lambda c: (c["cost_uusd"], -c["score"]), default=None)


def agentic_score(candidate: dict) -> float | None:
    """AutomationBench-AA and Terminal-Bench 4.0, averaged; None unless both were run."""
    automation, terminal = candidate.get("automation_bench"), candidate.get("terminal_bench")
    if automation is None or terminal is None:
        return None
    return round((automation + terminal) / 2, 1)


def subagent_bar(candidates: list[dict]) -> dict | None:
    """The agentic score a subagent has to reach: SUBAGENT_BAR of the agentic leader's."""
    scored = [c for c in candidates if agentic_score(c) is not None]
    leader = max(scored, key=lambda c: (agentic_score(c), -c["cost_uusd"]), default=None)
    if leader is None:
        return None
    return {
        "share": SUBAGENT_BAR,
        "score": round(agentic_score(leader) * SUBAGENT_BAR, 1),
        "leader": leader["label"],
        "leader_score": agentic_score(leader),
    }


def _why(
    role: str,
    per_task_budget: float,
    per_task: float,
    drift_replaced: dict | None = None,
    speed_blocked: dict | None = None,
    ceiling: float | None = None,
    bar: dict | None = None,
    under_bar: bool = False,
) -> str:
    """Why this model, in this role, at this tier — in the terms the budget is managed in."""
    # Terse on purpose. The card is read at a glance and the rules are spelled out in the
    # method panel; four sentences of reasoning per card pushed the verdict below the fold.
    price = f"{per_task:.0f} cr/task"
    if role == "architect":
        base = f"Best the planning share affords: {price}, ceiling {per_task_budget:.0f}."
    elif role == "worker":
        base = f"Climbs while a point costs at most ${FAIR_USD_PER_PP:.2f}. Lands at {price}."
    elif under_bar:
        base = (
            f"Nothing at {bar['share']:.0%} of the agentic leader ({bar['score']:.1f}) fits this "
            f"patience — the best agentic score that does. {price}."
        )
    else:
        base = (
            f"From {bar['share']:.0%} of the agentic leader ({bar['score']:.1f}), climbs while an "
            f"agentic point costs at most ${FAIR_USD_PER_PP:.2f}. Lands at {price}."
        )
    if speed_blocked and speed_blocked["task_minutes"] is None:
        base += (
            f" Not {speed_blocked['label']} ({speed_blocked['score']:.1f}): not timed, so "
            f"nothing says it stays within the {ceiling:g} min this patience allows."
        )
    elif speed_blocked:
        base += (
            f" Not {speed_blocked['label']} ({speed_blocked['score']:.1f}): "
            f"{speed_blocked['task_minutes']:g} min a task, over the {ceiling:g} min this "
            "patience allows."
        )
    if drift_replaced:
        base += f" Not {drift_replaced['label']} — sliding on AI Stupid Level."
    return base


def _below(upper: dict, candidate: dict) -> bool:
    """Does `candidate` sit at or under `upper` on both score and price per task?"""
    return candidate["score"] <= upper["score"] and candidate["cost_uusd"] <= upper["cost_uusd"]


def _loop_pool(candidates: list[dict], ceiling: float | None, score=lambda c: c["score"]) -> list[dict]:
    """The frontier a loop role climbs: rebuilt without the variants too slow to iterate with.

    Filtering the finished frontier would be wrong — a slow rung removed from it can hide a
    quick variant it used to dominate, and that variant is exactly the one this role wants.
    """
    return frontier([c for c in candidates if quick_enough(c, ceiling)], score)


def quick_option(pick: dict, candidates: list[dict]) -> dict | None:
    """The worker's model at an effort that runs a task in QUICK_SHARE of the time, or less.

    For renames, commit messages and "where is this" — the work the scout used to take. The
    best-scoring such effort; None when the pick is untimed or nothing is that quick.
    """
    minutes = loop_minutes(pick)
    if minutes is None:
        return None
    quick = [
        c for c in candidates
        if c["key"] == pick["key"] and c is not pick
        and loop_minutes(c) is not None and loop_minutes(c) <= minutes * QUICK_SHARE
    ]
    return max(quick, key=lambda c: (c["score"], -c["cost_uusd"]), default=None)


def _subagent(candidates: list[dict], ceiling: float | None, bar: dict | None, architect: dict | None = None):
    """The subagent: from the cheapest variant over the agentic bar, up the agentic ladder.

    Returns (pick, under_bar, speed_blocked). Not bound by a budget share: it is what the
    architect delegates to, so it is priced into throughput rather than into the base day. It
    never costs more per task than the architect, and is never the architect's own variant:
    delegating to a dearer model is not delegation. Without that, at Any pace the agentic
    ladder climbed onto Gemini 4 Carbon · High, the architect itself, at 36 minutes a task.
    """
    scored = [
        c for c in candidates
        if agentic_score(c) is not None
        and (
            architect is None
            or (c["cost_uusd"] <= architect["cost_uusd"]
                and (c["key"], c["effort"]) != (architect["key"], architect["effort"]))
        )
    ]
    rungs = _loop_pool(scored, ceiling, agentic_score)
    over = [c for c in rungs if bar and agentic_score(c) >= bar["score"]]
    under_bar = not over
    if over:
        pick = _climb(over, FAIR_USD_PER_PP, agentic_score)
    else:
        pick = max(rungs, key=lambda c: (agentic_score(c), -c["cost_uusd"]), default=None)
        under_bar = pick is not None
    # What patience cost it: the best fair step up that takes too long.
    slow = [
        c
        for c in scored
        if pick is not None
        and not quick_enough(c, ceiling)
        and agentic_score(c) > agentic_score(pick)
        and (c["cost_uusd"] - pick["cost_uusd"]) / 1_000_000
        <= (agentic_score(c) - agentic_score(pick)) * FAIR_USD_PER_PP
    ]
    blocked = max(slow, key=lambda c: (agentic_score(c), -c["cost_uusd"]), default=None)
    speed_blocked = (
        {"label": blocked["label"], "score": agentic_score(blocked), "task_minutes": loop_minutes(blocked)}
        if blocked
        else None
    )
    return pick, under_bar, speed_blocked


def _reference(candidates: list[dict], credit_usd: float, patience: dict) -> dict:
    """What each role would run with no budget at all — the merit-only shortlist.

    The same rules as the plan with the tier taken away: the architect takes the best on the
    board, the worker climbs its ladder as far as the per-point discipline lets it. Its cost is
    the number that says whether the tier, and not the data, picks your models.
    """
    return {
        "architect": max(candidates, key=lambda c: (c["score"], -c["cost_uusd"]), default=None),
        "worker": _walk_ladder(
            _loop_pool(candidates, patience["worker"]), float("inf"), credit_usd, FAIR_USD_PER_PP
        ),
    }


def plan_for_tier(
    tier: dict,
    candidates: list[dict],
    credit_usd: float,
    patience_id: str = DEFAULT_PATIENCE,
    drift_trusted: bool = True,
) -> dict:
    """Fill the three roles for one tier, at one patience setting.

    The architect and the worker are sized on the base day, inside their shares; the subagent
    is outside it, and the rest of the day's allowance is reported as throughput.
    `candidates` must all carry a cost: a variant nobody has priced cannot be budgeted, so it
    never reaches this function.
    """
    patience = PATIENCE[patience_id]
    ceiling = patience["worker"]
    monthly = tasks_per_month()
    roles = {}
    total_credits = 0.0
    board_best = max(candidates, key=lambda c: (c["score"], -c["cost_uusd"]), default=None)
    rungs = frontier(candidates)

    state: dict[str, dict] = {}
    for role in ("architect", "worker"):
        share_credits = tier["credits"] * BUDGET_SHARES[role]
        billable_tasks = monthly[role] * OVERHEAD
        per_task = share_credits / billable_tasks if billable_tasks else 0.0
        if role == "architect":
            pick = _best_affordable(candidates, per_task, credit_usd)
            pool = [c for c in candidates if _fits(c, per_task, credit_usd)]
        else:
            quick = _loop_pool(candidates, ceiling)
            pick = _walk_ladder(quick, per_task, credit_usd, FAIR_USD_PER_PP)
            pool = [c for c in quick if _fits(c, per_task, credit_usd)]
        drift_replaced = None
        if pick is not None:
            # The budget decides what is affordable; drift still decides what is sane.
            pick, drift_replaced = _avoid_drift(pick, pool, drift_trusted)
        state[role] = {
            "pick": pick,
            "pool": pool,
            "drift_replaced": drift_replaced,
            "ceiling": ceiling if role == "worker" else None,
            "share_credits": share_credits,
            "billable_tasks": billable_tasks,
            "per_task": per_task,
            "speed_blocked": None,
        }

    # The worker never scores more or costs more than the architect; if its opening pick breaks
    # that, it steps down to the best in its pool that does not, or shares the architect's pick
    # (said once on the card) when nothing does.
    above, pick = state["architect"]["pick"], state["worker"]["pick"]
    if above and pick and not _below(above, pick):
        fitting = [c for c in state["worker"]["pool"] if _below(above, c)]
        state["worker"]["pick"] = (
            max(fitting, key=lambda c: (c["score"], -c["cost_uusd"])) if fitting else above
        )

    # What patience cost the worker, so the card can say it rather than just differ: the best
    # model it could otherwise have taken — affordable, below the architect — that takes too
    # long per task.
    worker = state["worker"]
    ignored = [
        c
        for c in rungs
        if not quick_enough(c, ceiling)
        and _fits(c, worker["per_task"], credit_usd)
        and (worker["pick"] is None or c["score"] > worker["pick"]["score"])
        and (above is None or _below(above, c))
        and not (above and c["key"] == above["key"] and c["effort"] == above["effort"])
    ]
    best = max(ignored, key=lambda c: c["score"], default=None)
    if best:
        worker["speed_blocked"] = {
            "label": best["label"],
            "score": best["score"],
            "task_minutes": loop_minutes(best),
        }

    for role in ("architect", "worker"):
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

        # The architect's rule is "buy the best you can afford", so naming the model it could
        # not afford is informative. The worker stops climbing for economic reasons, not
        # budget ones — telling it about a model it deliberately did not want would be noise.
        out_of_reach = None
        if role == "architect" and board_best is not None and board_best["key"] != pick["key"]:
            best_price = credits_for(board_best["cost_uusd"], credit_usd)
            if best_price is not None and best_price > per_task:
                out_of_reach = {
                    "label": board_best["label"],
                    "score": board_best["score"],
                    "per_task_credits": round(best_price),
                    "ceiling_credits": round(max(per_task, 0)),
                }
        roles[role] = {
            "pick": pick,
            "why": _why(
                role, per_task, per_task_credits, drift_replaced,
                slot["speed_blocked"], slot["ceiling"],
            ),
            "drift_replaced": drift_replaced["label"] if drift_replaced else None,
            "speed_blocked": slot["speed_blocked"],
            "ceiling_minutes": slot["ceiling"],
            "out_of_reach": out_of_reach,
            "share_credits": round(share_credits),
            "per_task_budget_credits": round(per_task),
            "per_task_credits": round(per_task_credits, 1),
            "tasks_per_month": monthly[role],
            "month_credits": round(month_credits),
            "month_usd": round(month_credits * credit_usd, 2),
            "share_used_pct": round(100 * month_credits / share_credits, 1) if share_credits else None,
        }

    work, plan_pick = roles["worker"].get("pick"), roles["architect"].get("pick")
    if work and plan_pick and work["key"] == plan_pick["key"] and work["effort"] == plan_pick["effort"]:
        # At a tight budget the two collapse onto one model. That is an answer, not a bug.
        roles["worker"]["same_as"] = "architect"
    if work:
        quick = quick_option(work, candidates)
        if quick:
            roles["worker"]["quick"] = {
                "label": quick["label"],
                "effort_label": quick["effort_label"],
                "score": quick["score"],
                "task_minutes": loop_minutes(quick),
                "per_task_credits": round(credits_for(quick["cost_uusd"], credit_usd), 1),
            }

    # The subagent sits outside the base day: it is what the spare allowance is spent on.
    sub_bar = subagent_bar(candidates)
    sub_pick, sub_under, sub_blocked = _subagent(candidates, ceiling, sub_bar, plan_pick)
    if sub_pick is None:
        roles["subagent"] = {
            "pick": None,
            "why": "No model on the board has been run on both agentic evaluations.",
        }
    else:
        sub_credits = credits_for(sub_pick["cost_uusd"], credit_usd)
        roles["subagent"] = {
            "pick": sub_pick,
            "agentic_score": agentic_score(sub_pick),
            "why": _why("subagent", sub_credits, sub_credits, None, sub_blocked, ceiling, sub_bar, sub_under),
            "drift_replaced": None,
            "speed_blocked": sub_blocked,
            "ceiling_minutes": ceiling,
            "out_of_reach": None,
            "per_task_credits": round(sub_credits, 1),
            "bar": sub_bar,
            "under_bar": sub_under,
        }

    # Throughput: the day's allowance, what the base day takes of it, and what the rest buys
    # if spent on one role alone. That is the tier's real answer — more runs, not a reserve.
    day_credits = tier["credits"] / WORKING_DAYS if WORKING_DAYS else 0.0
    base_day = total_credits / WORKING_DAYS if WORKING_DAYS else 0.0
    spare_day = max(day_credits - base_day, 0.0)
    extra_per_day = {}
    for role in ("worker", "subagent", "architect"):
        price = roles.get(role, {}).get("per_task_credits")
        if price:
            extra_per_day[role] = int(spare_day / (price * OVERHEAD))
    for role, extra in extra_per_day.items():
        roles[role]["extra_per_day"] = extra

    # What the merit-only shortlist would cost here — the number that says whether the tier,
    # and not the benchmark, is the thing deciding your models.
    reference_credits = 0.0
    for role, pick in _reference(candidates, credit_usd, patience).items():
        price = credits_for(pick["cost_uusd"], credit_usd) if pick else None
        if price is not None:
            reference_credits += price * monthly[role] * OVERHEAD

    return {
        **tier,
        "patience": patience_id,
        "usd": round(tier["credits"] * credit_usd, 2),
        "roles": roles,
        "month_credits": round(total_credits),
        "month_usd": round(total_credits * credit_usd, 2),
        "reference_credits": round(reference_credits),
        "reference_used_pct": round(100 * reference_credits / tier["credits"], 1) if tier["credits"] else None,
        "reference_fits": reference_credits <= tier["credits"],
        "day_credits": round(day_credits),
        "base_day_credits": round(base_day),
        "spare_day_credits": round(spare_day),
        "extra_per_day": extra_per_day,
    }


def plans(
    tiers: list[dict],
    candidates: list[dict],
    credit_usd: float,
    drift_trusted: bool = True,
) -> dict:
    """Every tier at every patience setting: plans[tier][patience]. Nine small plans."""
    return {
        tier["id"]: {
            patience_id: plan_for_tier(tier, candidates, credit_usd, patience_id, drift_trusted)
            for patience_id in PATIENCE
        }
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
        "subagent_bar": SUBAGENT_BAR,
        "quick_share": QUICK_SHARE,
        "patience": PATIENCE,
        "default_patience": DEFAULT_PATIENCE,
    }
