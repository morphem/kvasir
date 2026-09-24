"""One verdict out of three sources.

The rules are deliberately few and deliberately visible — every threshold used here is
echoed into the API response so the page can show its own reasoning instead of asking to
be trusted. Nothing is hand-tuned per model: change the benchmark numbers and the verdict
changes with them, which is the whole point of archiving them.

Quality, cost and time come from Artificial Analysis: the Intelligence Index score, the cost of
one index task, and the wait before the first answer token — all per effort, all from the same
runs. Drift is AI Stupid Level's current score and trend, used as a veto rather than as another
number to average in — a model that is quietly getting worse this week should not win on last
month's benchmark. GitHub's Copilot page decides what is on the board at all.

The roles themselves are filled in `budget.py`, once per tier and patience setting; this module
builds the board they are filled from, and the views of it the page draws.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import budget, db
from .catalog import TASKS, TIER_BY_ID, TIERS
from .naming import EFFORT_LABELS, vendor_of
from .naming import label as model_label


def _usd(uusd: int | None) -> float | None:
    return None if uusd is None else round(uusd / 1_000_000, 4)


EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}


def _task_floor(row: dict, timed: dict[str, dict[str, float]]) -> tuple[float, str] | None:
    """For a variant nobody timed: the longest task time of a lower effort of the same model.

    Reasoning effort is the waiting, so raising it does not make a task shorter — an untimed
    Max takes at least as long as a timed Extra High. Without this floor the rule "unmeasured
    is not slow" put Opus 5.5 · Max, the slowest variant on the board, into a Fast worker's
    seat the day its High crossed the ceiling. A model with no timed effort at all still
    passes: that is absence of evidence, and it decides nothing.
    """
    rank = EFFORT_ORDER.get(row["effort"])
    if rank is None:
        return None
    lower = [
        (seconds, effort)
        for effort, seconds in timed.get(row["model_key"], {}).items()
        if EFFORT_ORDER.get(effort, 99) < rank
    ]
    return max(lower) if lower else None


def _speed_block(row: dict, family: dict | None, floor: tuple[float, str] | None) -> dict | None:
    """What we know about this exact variant's clocks, and at what setting we know each.

    Time per task — one loop of an agent, the clock patience is set on — and the wait to the
    first answer are the variant's own: reasoning effort *is* the waiting, so lending one
    effort's clock to another would be a fiction. The one exception is the floor above, which
    is a lower bound and labelled as one. Typing speed is a property of the model and its
    hardware, so a variant that was not timed borrows its family's, and says which effort
    that came from.
    """
    own_speed = row.get("tokens_per_second")
    source = row if own_speed else family
    task_seconds = row.get("task_seconds")
    block = {
        "task_minutes": round(task_seconds / 60, 1) if task_seconds else None,
        "task_minutes_floor_from": None,
        "tokens_per_second": source.get("tokens_per_second") if source else None,
        "measured_effort": source.get("effort") if source else None,
        "first_answer_seconds": row.get("first_answer_seconds"),
        "end_to_end_seconds": row.get("end_to_end_seconds"),
        "thinking_seconds": row.get("thinking_seconds"),
    }
    if not task_seconds and floor:
        block["task_minutes"] = round(floor[0] / 60, 1)
        block["task_minutes_floor_from"] = floor[1]
    keys = ("task_minutes", "tokens_per_second", "first_answer_seconds", "end_to_end_seconds")
    return block if any(block[k] for k in keys) else None


def merge(
    aa_rows: list[dict], ai_rows: list[dict], cp_rows: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Join the three sources on the canonical model key.

    Returns (candidates, copilot_only). A candidate is one model at one named effort with an
    index score; a variant without an effort (a non-reasoning mode) is archived but never a
    candidate, because no number is shown without its effort. The second list is what we can
    pick at work but nobody has scored, which is a fact worth showing rather than hiding.
    """
    drift_by_model = {row["model_key"]: row for row in ai_rows}
    copilot_by_model: dict[str, dict] = {}
    for row in cp_rows:
        tier = (row.get("tier") or "Default").lower()
        if not tier.startswith("default"):
            continue  # long-context pricing is a variant, not a different model
        copilot_by_model.setdefault(row["model_key"], row)

    family_speed: dict[str, dict] = {}
    timed: dict[str, dict[str, float]] = {}
    for row in aa_rows:
        if row["effort"] == "default":
            continue
        if row.get("tokens_per_second"):
            family_speed.setdefault(row["model_key"], row)
        if row.get("task_seconds"):
            timed.setdefault(row["model_key"], {})[row["effort"]] = row["task_seconds"]

    candidates = []
    for row in aa_rows:
        if row["effort"] == "default" or row.get("score") is None:
            continue
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
                "score": row["score"],
                "terminal_bench": row.get("terminal_bench"),
                "cost_uusd": row.get("cost_uusd"),
                "cost_usd": _usd(row.get("cost_uusd")),
                # Artificial Analysis times a new release before it prices it. Such a variant
                # is on the board, never in a role: a budget cannot be planned on no price.
                "priced": row.get("cost_uusd") is not None,
                "output_tokens": row.get("output_tokens"),
                "deprecated": row.get("deprecated", False),
                "released": row.get("released", ""),
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
                "speed": _speed_block(row, family_speed.get(key), _task_floor(row, timed)),
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

    scored = {c["key"] for c in candidates}
    copilot_only = []
    for key, row in sorted(copilot_by_model.items()):
        if key in scored:
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


# A drift reading older than this is history, not a signal: it would keep vetoing the same
# model for as long as the source stays down. Two days covers a weekend outage.
DRIFT_TRUST_HOURS = 48


def drift_freshness(ai_rows: list[dict]) -> tuple[str | None, float | None]:
    """How old the drift source's own newest measurement is, in hours."""
    stamps = []
    for row in ai_rows:
        raw = row.get("last_updated")
        if not raw:
            continue
        try:
            stamps.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except ValueError:
            continue
    if not stamps:
        return None, None
    newest = max(stamps)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
    return newest.isoformat(timespec="seconds"), round(age, 1)


AVAILABLE = "available"
NOT_IN_COPILOT = "not-in-copilot"
NOT_ENABLED = "not-enabled"

AVAILABILITY_LABELS = {
    NOT_IN_COPILOT: "not in Copilot",
    NOT_ENABLED: "not enabled for us",
}


def in_family(key: str, family: str) -> bool:
    """Does this model key belong to a disabled family?

    Families, not exact keys: "fable" covers fable-5 and fable-5.1, and "fable-5" still
    covers fable-5.1. Vendors ship point releases faster than anyone updates a list, and an
    exact-match list silently promotes the new version into the verdict — which is exactly
    how fable-5.1 became the recommended architect.
    """
    key, family = key.lower(), family.lower()
    return key == family or key.startswith(family + "-") or key.startswith(family + ".")


def availability(candidate: dict, disabled: list[str]) -> str:
    """Can we actually start this model at work?

    A model absent from GitHub's Copilot pricing page is not on our board at all — that is
    data, not opinion. `disabled` only carries what GitHub does sell us and the
    organisation has switched off.
    """
    if not candidate.get("copilot"):
        return NOT_IN_COPILOT
    if any(in_family(candidate["key"], family) for family in disabled):
        return NOT_ENABLED
    return AVAILABLE


frontier = budget.frontier


def value_ladder(candidates: list[dict]) -> list[dict]:
    """The cost/quality frontier, rung by rung.

    Each step answers one question: how much does the next point of Intelligence Index cost
    here. That is where "pay pennies more, get a much better result" becomes visible — and
    where paying five times more for half a point becomes visible too.
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
            "output_tokens": candidate["output_tokens"],
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
    """The same two thresholds the loop roles climb by — one discipline, not two."""
    if per_pp is None:
        return "flat"
    usd_per_pp = per_pp / 1_000_000
    if usd_per_pp <= budget.BARGAIN_USD_PER_PP:
        return "bargain"
    if usd_per_pp <= budget.FAIR_USD_PER_PP:
        return "fair"
    return "steep"


def gaps(roles: dict) -> list[dict]:
    """The distance between the roles — the thing that decides whether to escalate."""
    out = []
    for lower, upper in (("scout", "worker"), ("worker", "architect")):
        if lower not in roles or upper not in roles:
            continue
        low, high = roles[lower]["pick"], roles[upper]["pick"]
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


def _decision(payload: dict) -> dict:
    """The part of a view that is a decision: who won which role, at what price.

    Freshness counters, timestamps and the "why" prose are deliberately left out — they
    move on every render and would turn the change log into noise. The credit rate is kept,
    because a change that moves every pick must stay explainable from the archived record.
    """

    def core(pick: dict | None) -> dict | None:
        if not pick:
            return None
        return {
            "key": pick["key"],
            "effort": pick["effort"],
            "label": pick["label"],
            "score": pick["score"],
            "cost_uusd": pick["cost_uusd"],
        }

    return {
        "plans": {
            tier_id: {
                patience_id: {role: core(data.get("pick")) for role, data in plan["roles"].items()}
                for patience_id, plan in by_patience.items()
            }
            for tier_id, by_patience in payload["plans"].items()
        },
        "credit_usd": payload["credit_usd"],
        "thresholds": payload["thresholds"],
    }


def capture(db_path: str, cfg) -> bool:
    """Archive the current verdict if it differs from the last one stored.

    Reads only from the archive, so it can run after any collection round without
    touching the network; dedup means an unchanged reading costs one hash. Returns
    whether a new decision was written.
    """
    aa_rows, _ = db.latest(db_path, "artificialanalysis")
    ai_rows, _ = db.latest(db_path, "stupidlevel")
    cp_rows, cp_meta = db.latest(db_path, "copilot")
    if not (aa_rows and ai_rows and cp_rows):
        return False  # an incomplete board has no verdict worth writing down
    view = build(aa_rows, ai_rows, cp_rows, cfg, cfg.disabled_models, cp_meta.get("credit_usd"))
    _, changed = db.archive_recommendation(db_path, _decision(view))
    return changed


def build(
    aa_rows,
    ai_rows,
    cp_rows,
    cfg,
    disabled: list[str],
    credit_usd: float | None = None,
    show_all: bool = False,
) -> dict:
    candidates, copilot_only = merge(aa_rows, ai_rows, cp_rows)

    # Availability is only knowable while we hold GitHub's model list. On a cold start, or
    # if that source ever fails before its first snapshot, an empty board would be a worse
    # lie than an unfiltered one — so the filter stands down and the payload says so.
    availability_known = bool(cp_rows)
    for candidate in candidates:
        state = availability(candidate, disabled) if availability_known else AVAILABLE
        candidate["availability"] = state
        candidate["available"] = state == AVAILABLE
        candidate["unavailable_reason"] = AVAILABILITY_LABELS.get(state)

    # The default board is what we can actually start today. Recommending a model nobody
    # here can run is worse than recommending nothing: it reads as advice and cannot be
    # taken. `show_all` opens the board so the cost of the restriction stays visible — the
    # current models, that is: six hundred retired variants would bury the comparison.
    if show_all:
        visible = [c for c in candidates if c["available"] or c["copilot"] or not c["deprecated"]]
        excluded = []
    else:
        visible = [c for c in candidates if c["available"]]
        # What GitHub sells us and the organisation switched off: a choice worth showing.
        excluded = [c for c in candidates if not c["available"] and c["copilot"]]
    priced = [c for c in visible if c["priced"]]
    # The rest of the market, for scale on the charts only: current models we cannot start,
    # one variant each (their best-scoring priced one), never planned and never in a table.
    shown = {c["key"] for c in visible}
    market: dict[str, dict] = {}
    for c in candidates:
        if c["key"] in shown or c["deprecated"] or not c["priced"]:
            continue
        if c["key"] not in market or c["score"] > market[c["key"]]["score"]:
            market[c["key"]] = c
    drift_newest, drift_age_hours = drift_freshness(ai_rows)
    drift_trusted = drift_age_hours is not None and drift_age_hours <= DRIFT_TRUST_HOURS

    rate = credit_usd or budget.CREDIT_USD_FALLBACK
    plans = budget.plans(cfg.tiers, priced, rate, drift_trusted=drift_trusted)
    for by_patience in plans.values():
        for plan in by_patience.values():
            # The distance between roles is worth seeing per tier: on a tight budget two roles
            # can land on one model, and then the gap is genuinely zero.
            picks = {role: data for role, data in plan["roles"].items() if data.get("pick")}
            plan["gaps"] = gaps(picks)
    return {
        "credit_usd": rate,
        "credit_usd_verified": credit_usd is not None,
        "budget_tiers": cfg.tiers,
        "default_tier": cfg.default_tier,
        "patience": [{"id": pid, **p} for pid, p in budget.PATIENCE.items()],
        "default_patience": cfg.default_patience
        if cfg.default_patience in budget.PATIENCE
        else budget.DEFAULT_PATIENCE,
        "plans": plans,
        "assumptions": budget.assumptions(rate),
        "tiers": TIERS,
        "tasks": [
            {**task, "tier_name": TIER_BY_ID[task["tier"]]["name"], "accent": TIER_BY_ID[task["tier"]]["accent"]}
            for task in TASKS
        ],
        "ladder": value_ladder(priced),
        "candidates": sorted(visible, key=lambda c: -c["score"]),
        "unpriced": sorted(
            ({"key": c["key"], "label": c["label"], "released": c["released"]} for c in visible if not c["priced"]),
            key=lambda c: c["label"],
        ),
        "excluded": sorted(excluded, key=lambda c: -c["score"]),
        "market": [
            {
                "key": c["key"], "label": c["label"], "score": c["score"],
                "cost_usd": c["cost_usd"], "output_tokens": c["output_tokens"],
                "task_minutes": (c["speed"] or {}).get("task_minutes"),
                "reason": c["unavailable_reason"],
            }
            for c in sorted(market.values(), key=lambda c: -c["score"])
        ],
        "availability_known": availability_known,
        "drift_trusted": drift_trusted,
        "drift_age_hours": drift_age_hours,
        "drift_newest": drift_newest,
        "all_candidates_count": len(candidates),
        "disabled_families": sorted({f.lower() for f in disabled}),
        "copilot_only": copilot_only,
        "thresholds": {
            "bargain_usd_per_pp": budget.BARGAIN_USD_PER_PP,
            "fair_usd_per_pp": budget.FAIR_USD_PER_PP,
        },
    }
