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

So a tier's dollar equivalent is just `credits × $0.01`, and the organisation's three tiers check
out exactly: **Basic** 13,000 → $130, **Heavy** 100,000 → $1,000, **Power** 200,000 → $2,000.

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
   Practically: Basic/Heavy/Power are allocations out of the company pool, and a light month by
   one engineer subsidises a heavy month by another.

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

A "task" is one **Artificial Analysis Intelligence Index task**: the weighted average of one task
across the index's ten evaluations — some agentic and long (AA-Briefcase, Terminal-Bench,
AutomationBench), some a single hard question. That is a heavier unit than a chat question, which
is why the overhead factor exists rather than a second made-up task type.

**The unit has changed twice, and a projection is only comparable within one unit.**

1. **2026-09-10, CursorBench 3.2 → 4.0.** 4.0 added long-horizon problems and a task became roughly
   twice the work: steps per task rose about 70% (Opus 5 · Max 78 → 106) and cost per task between
   10% and 160%. The top score fell from 70.8% to 51.8%.
2. **2026-09-22, CursorBench → Artificial Analysis.** The board is now scored by the Intelligence
   Index (v4.3) and priced by the cost of one index task. The magnitudes are similar — Opus 5 · Max
   is $5.86 a task here — but it is a different benchmark with a different task mix, and scores
   are index points, not percentages.

Neither is a reason to re-tune the constants above. Six tasks a day stays six tasks a day, printed
next to its answer; a projection made before 22 September and one made after are not measuring
the same month. If the real workload is ever measured from Copilot's usage metrics, replace the
model — do not adjust `TASKS_PER_DAY` to keep an old number looking familiar across a source change.

The two per-point ceilings below ($0.75 and $0.15 a point) were set on CursorBench's scale. The
Intelligence Index spans a similar range (about 20 to 58 on our board), so they carry over, but they
were not re-derived — treat that as an open question, not as a tuned result.

## How each role is filled

- **Architect** — the highest-scoring model its share of the budget can pay for. Where planning is
  concerned, buy the best you can afford. Never on the patience clock.
- **Worker** — climbs the cost/quality frontier while each step costs at most **$0.75 per
  point** and still fits its share.
- **Scout** — climbs only while a step is a **bargain (≤ $0.15 per point)**. Mechanical work does
  not repay more.
- **Patience** — the worker and the scout only climb a frontier rebuilt from the variants that
  answer inside the selected wait: **Fast** 30 s / 10 s, **Balanced** 90 s / 30 s, **Any** no limit
  (worker / scout, seconds to the first answer token). A variant nobody has timed passes.
- **Surplus** — once the economical picks are in, the plan spends the tier up to 80%, architect
  first, and never past 90%. A lower role may not score more, or cost more per task, than the role
  above it, and may not land on another role's exact variant.

Both per-point ceilings are the same thresholds the value ladder shows on the page, so nothing here
is a private knob.

## What that produces for these tiers (data of 2026-09-22, Balanced patience)

| Tier | Architect | Worker | Scout | Month | Used |
|---|---|---|---|---|---|
| **Basic** 13K | Opus 5.5 · Extra High | Opus 5.5 · Low | GPT-5.6 Terra · High | ~10,960 cr ≈ $110 | **84%** |
| **Heavy** 100K | Opus 5.5 · Max | Opus 5.5 · High | Opus 5.5 · Medium | ~29,600 cr ≈ $296 | **30%** |
| **Power** 200K | Opus 5.5 · Max | Opus 5.5 · High | Opus 5.5 · Medium | ~29,600 cr ≈ $296 | **15%** |

At **Any** patience, Basic's scout becomes GPT-5.6 Luna · Max (18 credits, but 116 s before it
answers) and Heavy/Power buy Opus 5.5 · Extra High for the worker (~44,300 cr). At **Fast**, Heavy's
scout drops to Opus 5.5 · Low (~25,100 cr).

Four conclusions worth arguing about at work:

1. **Opus 5.5 leads at every price from $0.55 a task up.** On Artificial Analysis's frontier it holds
   every rung from Low to Max, so on a roomy tier all three roles are Opus 5.5 at three efforts.
   That is the data, not a collapsed board: effort is the dial between the roles.
2. **Basic is enough for the average engineer.** The merit-only shortlist costs ~29,600 credits
   (228% of Basic), so at Basic the budget picks the models — and it still plans on Opus 5.5 for
   the architect and the worker.
3. **Heavy and Power stop at 15–30% because of the wait, not the money.** The next step up is
   Opus 5.5 · Extra High, which thinks for 170 s before it answers; Balanced patience will not put
   that on a role you wait on all day. Choose Any and the tier is spent further; the plan says which
   rule stopped it next to the number.
4. **GPT-6 Luna and GPT-6 Sol are not in this table yet.** Artificial Analysis scored and timed them
   on release day (22 September) but has not priced them; they join the roles by themselves when it
   does. On score they sit where GPT-5.6 Luna and Sol do (Luna · Max 37.3 both; Sol · Max 47.5 vs
   47.0), at about half of Copilot's per-token price.

## The Luna effort question

Asked in August on CursorBench: is dropping GPT-5.6 Luna to a lower effort worth the saving? On
Artificial Analysis the answer turns on the wait rather than the credits:

| Luna effort | $/task | Credits/task | Intelligence | Wait to first answer |
|---|---|---|---|---|
| Max | $0.18 | 18 | 37.3 | 116 s |
| Extra High | $0.09 | 9 | 34.6 | 40 s |
| High | $0.04 | 4 | 32.1 | 15 s |
| Medium | $0.02 | 2 | 25.0 | 2.6 s |
| Low | $0.01 | 1 | 21.0 | 1.7 s |

Every effort is cheap next to any tier — the whole scout load at Max is about 1,000 credits a
month. What Max costs is two minutes of silence per request. For a role you wait on repeatedly,
**High** (15 s, 32.1) is the sensible Luna; Max belongs to a batch you do not sit and watch.

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
