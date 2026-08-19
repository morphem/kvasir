"""One verdict out of three sources.

The rules are deliberately few and deliberately visible — every threshold used here is
echoed into the API response so the page can show its own reasoning instead of asking to
be trusted. Nothing is hand-tuned per model: change the benchmark numbers and the verdict
changes with them, which is the whole point of archiving them.

Cost is CursorBench's average cost per task, the only end-to-end price any source
publishes. Quality is the CursorBench score. Drift is AI Stupid Level's current score and
trend, used as a veto rather than as another number to average in — a model that is
quietly getting worse this week should not win on last month's benchmark.
"""

from __future__ import annotations

from . import budget
from .catalog import TASKS, TIER_BY_ID, TIERS
from .naming import EFFORT_LABELS, label as model_label, vendor_of

SWAP_MAX_COST_FACTOR = 1.3

# Value-ladder verdicts, in micro-dollars per percentage point of CursorBench score.
BARGAIN_UUSD_PER_PP = 150_000      # under $0.15 per point — take the better model
STEEP_UUSD_PER_PP = 750_000        # over $0.75 per point — you are buying very little


def _usd(uusd: int | None) -> float | None:
    return None if uusd is None else round(uusd / 1_000_000, 4)


def merge(cb_rows: list[dict], ai_rows: list[dict], cp_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Join the three sources on the canonical model key.

    Returns (candidates, copilot_only) — the second list is models we can pick at work but
    that nobody has benchmarked end to end, which is a fact worth showing rather than
    hiding.
    """
    drift_by_model = {row["model_key"]: row for row in ai_rows}
    copilot_by_model: dict[str, dict] = {}
    for row in cp_rows:
        tier = (row.get("tier") or "Default").lower()
        if not tier.startswith("default"):
            continue  # long-context pricing is a variant, not a different model
        copilot_by_model.setdefault(row["model_key"], row)

    candidates = []
    for row in cb_rows:
        key = row["model_key"]
        drift = drift_by_model.get(key)
        copilot = copilot_by_model.get(key)
        candidates.append(
            {
                "key": key,
                "effort": row["effort"],
                "effort_label": EFFORT_LABELS.get(row["effort"], row["effort"]),
                "label": model_label(key, row["effort"]),
                "vendor": vendor_of(key),
                "rank": row["rank"],
                "score": row["score"],
                "cost_uusd": row["cost_uusd"],
                "cost_usd": _usd(row["cost_uusd"]),
                "tokens": row["tokens"],
                "steps": row["steps"],
                "drift": None
                if not drift
                else {
                    "score": drift.get("score"),
                    "trend": drift.get("trend"),
                    "status": drift.get("status"),
                    "stale": drift.get("is_stale"),
                    "ci_low": drift.get("ci_low"),
                    "ci_high": drift.get("ci_high"),
                },
                "copilot": None
                if not copilot
                else {
                    "available": True,
                    "category": copilot.get("category"),
                    "release_status": copilot.get("release_status"),
                    "input_usd": _usd(copilot.get("input_uusd")),
                    "cached_input_usd": _usd(copilot.get("cached_input_uusd")),
                    "output_usd": _usd(copilot.get("output_uusd")),
                },
            }
        )

    benchmarked = {row["model_key"] for row in cb_rows}
    copilot_only = []
    for key, row in sorted(copilot_by_model.items()):
        if key in benchmarked:
            continue
        copilot_only.append(
            {
                "key": key,
                "label": model_label(key, "default"),
                "vendor": vendor_of(key),
                "category": row.get("category"),
                "release_status": row.get("release_status"),
                "input_usd": _usd(row.get("input_uusd")),
                "cached_input_usd": _usd(row.get("cached_input_uusd")),
                "output_usd": _usd(row.get("output_uusd")),
                "drift": (drift_by_model.get(key) or {}).get("score"),
            }
        )
    return candidates, copilot_only


def _swap_for_drift(pick: dict, pool: list[dict]) -> tuple[dict, dict | None]:
    """If the winner is drifting, take the nearest non-drifting model instead."""
    if not budget.drifting(pick):
        return pick, None
    for other in sorted(pool, key=lambda c: -c["score"]):
        if other is pick or budget.drifting(other):
            continue
        if other["score"] < pick["score"] - budget.DRIFT_MAX_SCORE_LOSS_PP:
            continue
        if pick["cost_uusd"] and other["cost_uusd"] > pick["cost_uusd"] * SWAP_MAX_COST_FACTOR:
            continue
        return other, pick
    return pick, None


def pick_tiers(candidates: list[dict], cfg) -> dict:
    """Fill the three roles from the current data. Thresholds come from config."""
    if not candidates:
        return {}

    top_score = max(c["score"] for c in candidates)
    worker_cap = int(cfg.worker_max_cost_usd * 1_000_000)
    scout_cap = int(cfg.scout_max_cost_usd * 1_000_000)

    pools = {
        "architect": [c for c in candidates if c["score"] >= top_score - cfg.architect_score_slack_pp],
        "worker": [c for c in candidates if c["cost_uusd"] <= worker_cap],
        "scout": [c for c in candidates if c["cost_uusd"] <= scout_cap],
    }
    # A pool can come up empty once models are hidden; fall back to the cheapest available
    # rather than showing a hole, and say so.
    relaxed = set()
    for tier_id, pool in pools.items():
        if not pool:
            pools[tier_id] = sorted(candidates, key=lambda c: c["cost_uusd"])[:5]
            relaxed.add(tier_id)

    chooser = {
        "architect": lambda pool: min(pool, key=lambda c: (c["cost_uusd"], -c["score"])),
        "worker": lambda pool: max(pool, key=lambda c: (c["score"], -c["steps"])),
        "scout": lambda pool: max(pool, key=lambda c: (c["score"], -c["cost_uusd"])),
    }

    verdicts = {}
    for tier_id, pool in pools.items():
        raw_pick = chooser[tier_id](pool)
        pick, replaced = _swap_for_drift(raw_pick, pool)
        runner_up = next(
            (c for c in sorted(pool, key=lambda c: -c["score"]) if c["key"] != pick["key"]), None
        )
        verdicts[tier_id] = {
            "tier": TIER_BY_ID[tier_id],
            "pick": pick,
            "runner_up": runner_up,
            "replaced": replaced,
            "relaxed": tier_id in relaxed,
            "pool_size": len(pool),
            "why": _why(tier_id, pick, replaced, top_score, cfg),
        }

    # Overlapping ranges: when two roles land on the same model, say it once instead of
    # inventing a difference that the data does not support.
    for a, b in (("architect", "worker"), ("worker", "scout")):
        if verdicts.get(a) and verdicts.get(b) and verdicts[a]["pick"]["key"] == verdicts[b]["pick"]["key"]:
            same_effort = verdicts[a]["pick"]["effort"] == verdicts[b]["pick"]["effort"]
            verdicts[b]["overlap_with"] = a
            verdicts[b]["overlap_note"] = (
                f"Same model as the {TIER_BY_ID[a]['name'].lower()}"
                + (" at the same effort — the ranges overlap, there is nothing to split."
                   if same_effort else " — only the effort differs.")
            )
    return verdicts


def _why(tier_id: str, pick: dict, replaced: dict | None, top_score: float, cfg) -> str:
    cost = pick["cost_usd"]
    if tier_id == "architect":
        base = (
            f"Cheapest way into the top group: {pick['score']:.1f}% at ${cost:.2f} per task "
            f"(best today is {top_score:.1f}%, cutoff {cfg.architect_score_slack_pp:.0f} pp)."
        )
    elif tier_id == "worker":
        base = (
            f"Highest score that fits under ${cfg.worker_max_cost_usd:.2f} per task: "
            f"{pick['score']:.1f}% for ${cost:.2f}, {pick['steps']} steps."
        )
    else:
        base = (
            f"Highest score under ${cfg.scout_max_cost_usd:.2f} per task: "
            f"{pick['score']:.1f}% for ${cost:.2f}."
        )
    if replaced:
        base += (
            f" Instead of {replaced['label']} — that one is drifting down on AI Stupid Level, "
            "so today it is not worth the risk."
        )
    return base


def frontier(candidates: list[dict]) -> list[dict]:
    """The cost/quality frontier: models nothing else beats on price and score at once."""
    ordered = sorted(candidates, key=lambda c: (c["cost_uusd"], -c["score"]))
    out: list[dict] = []
    best = float("-inf")
    for candidate in ordered:
        if candidate["score"] > best:
            out.append(candidate)
            best = candidate["score"]
    return out


def value_ladder(candidates: list[dict]) -> list[dict]:
    """The cost/quality frontier, rung by rung.

    Each step answers one question: how much does the next percentage point cost here.
    That is where "pay pennies more, get a much better result" becomes visible — and where
    paying five times more for half a point becomes visible too.
    """
    rungs = []
    steps = frontier(candidates)
    for index, candidate in enumerate(steps):
        step = {
            "label": candidate["label"],
            "key": candidate["key"],
            "effort": candidate["effort"],
            "score": candidate["score"],
            "cost_usd": candidate["cost_usd"],
            "steps": candidate["steps"],
            "tokens": candidate["tokens"],
            "drift": candidate["drift"],
            "copilot": bool(candidate["copilot"]),
        }
        if index:
            previous = steps[index - 1]
            d_score = candidate["score"] - previous["score"]
            d_cost = candidate["cost_uusd"] - previous["cost_uusd"]
            per_pp = d_cost / d_score if d_score > 0 else None
            step.update(
                {
                    "from_label": previous["label"],
                    "delta_score_pp": round(d_score, 1),
                    "delta_cost_usd": _usd(d_cost),
                    "usd_per_pp": _usd(per_pp) if per_pp is not None else None,
                    "verdict": _ladder_verdict(per_pp),
                }
            )
        rungs.append(step)
    return rungs


def _ladder_verdict(per_pp: float | None) -> str:
    if per_pp is None:
        return "flat"
    if per_pp <= BARGAIN_UUSD_PER_PP:
        return "bargain"
    if per_pp <= STEEP_UUSD_PER_PP:
        return "fair"
    return "steep"


def gaps(verdicts: dict) -> list[dict]:
    """The distance between the roles — the thing that decides whether to escalate."""
    out = []
    for lower, upper in (("scout", "worker"), ("worker", "architect")):
        if lower not in verdicts or upper not in verdicts:
            continue
        low, high = verdicts[lower]["pick"], verdicts[upper]["pick"]
        d_score = round(high["score"] - low["score"], 1)
        d_cost = high["cost_uusd"] - low["cost_uusd"]
        per_pp = d_cost / d_score if d_score > 0 else None
        out.append(
            {
                "from": TIER_BY_ID[lower]["name"],
                "to": TIER_BY_ID[upper]["name"],
                "from_label": low["label"],
                "to_label": high["label"],
                "delta_score_pp": d_score,
                "delta_cost_usd": _usd(d_cost),
                "cost_factor": round(high["cost_uusd"] / low["cost_uusd"], 1) if low["cost_uusd"] else None,
                "usd_per_pp": _usd(per_pp) if per_pp is not None else None,
                "verdict": _ladder_verdict(per_pp),
            }
        )
    return out


def resolve_tasks(verdicts: dict) -> list[dict]:
    """The quick-answer table: a job on the left, the model to start on the right."""
    rows = []
    for task in TASKS:
        verdict = verdicts.get(task["tier"])
        if not verdict:
            continue
        pick = verdict["pick"]
        rows.append(
            {
                **task,
                "tier_name": TIER_BY_ID[task["tier"]]["name"],
                "accent": TIER_BY_ID[task["tier"]]["accent"],
                "pick_label": pick["label"],
                "pick_key": pick["key"],
                "pick_score": pick["score"],
                "pick_cost_usd": pick["cost_usd"],
                "pick_in_copilot": bool(pick["copilot"]),
                "overlap_note": verdict.get("overlap_note"),
            }
        )
    return rows


def build(cb_rows, ai_rows, cp_rows, cfg, hidden: list[str], credit_usd: float | None = None) -> dict:
    candidates, copilot_only = merge(cb_rows, ai_rows, cp_rows)
    hidden_set = {h.lower() for h in hidden}
    visible = [c for c in candidates if c["key"].lower() not in hidden_set]
    verdicts = pick_tiers(visible, cfg)
    rate = credit_usd or budget.CREDIT_USD_FALLBACK
    plans = budget.plans(cfg.tiers, visible, frontier(visible), rate, verdicts)
    for plan in plans.values():
        # The distance between roles is worth seeing per tier: on a tight budget two roles can
        # land on one model, and then the gap is genuinely zero.
        picks = {role: data for role, data in plan["roles"].items() if data.get("pick")}
        plan["gaps"] = gaps(picks)
    return {
        "credit_usd": rate,
        "credit_usd_verified": credit_usd is not None,
        "budget_tiers": cfg.tiers,
        "default_tier": cfg.default_tier,
        "plans": plans,
        "assumptions": budget.assumptions(rate),
        "tiers": TIERS,
        "verdicts": verdicts,
        "tasks": resolve_tasks(verdicts),
        "ladder": value_ladder(visible),
        "gaps": gaps(verdicts),
        "candidates": sorted(visible, key=lambda c: -c["score"]),
        "all_candidates_count": len(candidates),
        "hidden_models": sorted(hidden_set),
        "copilot_only": copilot_only,
        "thresholds": {
            "worker_max_cost_usd": cfg.worker_max_cost_usd,
            "scout_max_cost_usd": cfg.scout_max_cost_usd,
            "architect_score_slack_pp": cfg.architect_score_slack_pp,
            "bargain_usd_per_pp": BARGAIN_UUSD_PER_PP / 1_000_000,
            "steep_usd_per_pp": STEEP_UUSD_PER_PP / 1_000_000,
        },
    }
