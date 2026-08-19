# AI credits, tiers, and whether a tier survives a month

## The conversion is real, and the page reads it rather than assuming it

GitHub states the rate in one sentence on the pricing page, twice:

> When you use Copilot, the interaction consumes tokens: input tokens (what's sent to the model),
> output tokens (what the model generates), and cached tokens (context the model reuses or stores).
> Each token is priced based on the model used, and the total is converted into AI credits,
> **where 1 AI credit = $0.01 USD.**

> When usage exceeds the included allowances for any Copilot plan, additional usage is billed in
> GitHub AI Credits at the per-token rates shown in the pricing tables below (1 AI credit = $0.01 USD).

— <https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing>

So a tier's dollar equivalent is just `credits × $0.01`, and the numbers we were given check out
exactly: 13,000 → $130, 100,000 → $1,000, 200,000 → $2,000.

The collector parses that sentence out of the page (`kvasir/collectors/copilot.py`,
`_CREDIT_RATE`) and stores it with the snapshot, so the whole tier layer rests on a quoted fact
rather than a constant in our code. If GitHub ever changes the rate, the page says so instead of
being quietly wrong — and the footer prints the sentence it is standing on.

## Three other facts from the same docs that change the estimate

1. **Code completions and next edit suggestions are not billed in AI credits.** They "remain
   unlimited for all paid plans". Autocomplete is therefore *free* against the tier: the budget is
   spent by chat, agent mode, the CLI, cloud agents, Spaces, Spark, code review and third-party
   coding agents.
2. **Credits are pooled at the billing entity level, not per person.** GitHub's example: "an
   enterprise with 100 Copilot Business users gets a shared pool of 190,000 AI credits rather than
   100 individual buckets. This means power users can draw more when they need it, while lighter
   users offset that consumption."
3. **The included allowance per licence is small**: 1,900 credits/user/month on Copilot Business,
   3,900 on Copilot Enterprise — that is $19 and $39. A 13,000-credit tier is therefore an internal
   *allocation out of the pool* (and largely paid usage), not something a licence includes.
   [Source](https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-organizations-and-enterprises).

## The month we model

Nobody has a per-task meter, so the month is an explicit model, printed on the page next to its
own result (`kvasir/budget.py`):

| Assumption | Value | Why |
|---|---|---|
| Working days | 21 | one month |
| Agent tasks per day | 6 | the *average* engineer: one project or integration at a time, no parallel sessions |
| Role mix | 10% planning · 50% ordinary · 40% mechanical | matches the task catalogue on the page |
| Overhead | ×1.15 | chat, follow-ups and retries are billed but are not benchmark-shaped tasks |
| Budget split | 35% architect · 45% worker · 20% scout | planning is the smallest slice of tasks and the largest slice of value |

A "task" is a CursorBench task: a real, ambiguous, multi-file request, 20–100 agent steps. That is
a heavier unit than a chat question, which is why the overhead factor exists rather than a second
made-up task type.

## How each role is filled

- **Architect** — the highest-scoring model its share of the budget can pay for. Where planning is
  concerned, buy the best you can afford.
- **Worker** — climbs the cost/quality frontier while each step costs at most **$0.75 per
  percentage point** and still fits its share.
- **Scout** — climbs only while a step is a **bargain (≤ $0.15 per point)**. Mechanical work does
  not repay more.

Both ceilings are the same thresholds the value ladder shows on the page, so nothing here is a
private knob.

## What that produces (data of 2026-08-19)

| Tier | Architect | Worker | Scout | Month | Used |
|---|---|---|---|---|---|
| **Basic** 13K | GPT-5.6 Terra · Max | GPT-5.6 Luna · Max | GPT-5.6 Luna · Max | ~8,400 cr ≈ $84 | **65%** |
| **Heavy** 100K | Opus 5 · Max | GPT-5.6 Terra · Max | GPT-5.6 Luna · Max | ~30,900 cr ≈ $309 | **31%** |
| **Power** 200K | Opus 5 · Max | GPT-5.6 Terra · Max | GPT-5.6 Luna · Max | ~30,900 cr ≈ $309 | **15%** |

Three conclusions worth arguing about at work:

1. **Basic is enough for the average engineer — but only if Luna does the bulk.** The shortlist
   chosen on merit alone (Opus 5 · Extra High planning, Terra · Max working) costs ~29,600 credits
   a month: **228% of Basic**. At Basic the budget, not the benchmark, picks the models.
2. **Heavy affords the best board available and still leaves 69% unused.** For a single-project
   engineer it is not a constraint at all.
3. **Power buys nothing extra for this profile.** It only starts to matter for people who run
   several parallel sessions — a different workload, not a better model list.

## The Luna effort question

Dropping GPT-5.6 Luna to a lower effort to save credits is **not worth it at any tier**. Luna at
Max is 39 credits per task; the whole worker + scout load (113 tasks a month, overhead included) is
about 5,100 credits — 39% of Basic on its own. Lower efforts save single-digit credits per task and
give up real quality:

| Luna effort | $/task | Credits/task | CursorBench |
|---|---|---|---|
| Max | $0.39 | 39 | 61.1% |
| Extra High | $0.23 | 23 | 57.7% |
| High | $0.16 | 16 | 56.8% |
| Medium | $0.08 | 8 | 47.7% |
| Low | $0.03 | 3 | 37.6% |

Going Max → High saves 23 credits a task (~$0.23) and costs 4.3 points; Max → Medium saves 31
credits and costs 13.4 points. On a 13,000-credit tier those savings buy headroom nobody needs.
**Run Luna at Max.** The lower efforts are for a tier far smaller than Basic, or for a workload
several times heavier than this one.

## Tuning it for a different profile

Everything above is configuration:

```
KVASIR_TIERS="Basic:13000,Heavy:100000,Power:200000"
KVASIR_DEFAULT_TIER=heavy
```

The workload constants (days, tasks/day, mix, overhead, budget split, the two per-point ceilings)
live at the top of `kvasir/budget.py` and are printed on the page. If the real usage numbers ever
arrive from Copilot's usage metrics, replace the model — do not quietly re-tune the constants until
the answer looks nice.
