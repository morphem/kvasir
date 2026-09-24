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
  finish a task inside the selected time: **Fast** 3 / 1.5 minutes, **Balanced** 6 / 3, **Any** no
  limit (worker / scout, Artificial Analysis's time per index task). These are the roles you iterate
  with, so the length of one loop is the length of the job. A variant nobody timed passes, unless a
  lower effort of the same model already takes longer — then it is held to that time.
- **Surplus** — once the economical picks are in, the plan spends the tier up to 80%, architect
  first, and never past 90%. A lower role may not score more, or cost more per task, than the role
  above it, and may not land on another role's exact variant.

Both per-point ceilings are the same thresholds the value ladder shows on the page, so nothing here
is a private knob.

## What that produces for these tiers (data of 2026-09-24, Balanced patience)

| Tier | Architect | Worker | Scout | Month | Used |
|---|---|---|---|---|---|
| **Basic** 13K | Opus 5.5 · Extra High | GPT-6 Sol · Extra High | GPT-6 Sol · High | ~11,040 cr ≈ $110 | **85%** |
| **Heavy** 100K | Opus 5.5 · Max | Opus 5.5 · High | GPT-6 Sol · Extra High | ~24,960 cr ≈ $250 | **25%** |
| **Power** 200K | Opus 5.5 · Max | Opus 5.5 · High | GPT-6 Sol · Extra High | ~24,960 cr ≈ $250 | **12%** |

Minutes per task on those picks: the loop roles take 1.6–4.3 minutes; the architect 7.5 or more
(Opus 5.5 · Max is not timed and is held to its Extra High time). At **Fast** patience (3 / 1.5 min)
every tier runs GPT-6 Sol in both loop roles — Extra High for the worker, Medium for the scout —
and Heavy uses ~14,000 credits. At **Any**, Heavy/Power buy Opus 5.5 · Extra High for the worker and
Opus 5.5 · High for the scout (~44,300 cr).

Four conclusions worth arguing about at work:

1. **GPT-6 took the cheap half of the board.** Artificial Analysis priced GPT-6 Luna and Sol on
   23 September, a day after release. From half a cent to about a dollar a task the value frontier
   is now GPT-6 Luna, then GPT-6 Sol; only two GPT-5.6 Luna rungs survive, and Opus 5.5 · Low fell
   off it (GPT-6 Sol · High scores more for less). **Opus 5.5 leads from $1.34 a task up** —
   Medium through Max.
2. **Basic is enough for the average engineer, and runs its loops on GPT-6 Sol.** The merit-only
   shortlist costs ~25,000 credits (192% of Basic), so the budget picks the loop roles: GPT-6 Sol at
   Extra High (2.5 min a task) and High (1.6 min).
3. **Heavy and Power stop at 25% and 12% because of time, not money.** The next step up for the
   worker is Opus 5.5 · Extra High at 7.5 minutes a task, past Balanced's six; for the scout it is
   anything over three. The plan says so next to the number. Choose Any and the tier is spent
   further — at the price of loops that each take seven minutes.
4. **Times are medians, and they move.** Opus 5.5 · High's wait to its first answer went from
   12.7 s to 30.4 s in two days. Time per task comes from the index runs and moves less often, but
   a pick that sits near a patience ceiling can still flip without any price or score changing —
   that is the rule working, not noise.

## The Luna effort question

Asked in August on CursorBench: is dropping Luna to a lower effort worth the saving? On Artificial
Analysis the answer turns on the wait rather than the credits — and GPT-6 Luna answers it better
than GPT-5.6 Luna at almost every effort:

| Effort | GPT-5.6 Luna | GPT-6 Luna |
|---|---|---|
| Max | 17.8 cr · 37.3 · 114 s | 6.8 cr · 37.3 · 104 s |
| Extra High | 8.5 cr · 34.6 · 43 s | 4.2 cr · 33.9 · 17 s |
| High | 4.4 cr · 32.1 · 13 s | 2.9 cr · 32.1 · 7 s |
| Medium | 1.6 cr · 25.0 · 2.6 s | 1.7 cr · 29.5 · 5.3 s |
| Low | 1.0 cr · 21.0 · 1.7 s | 0.4 cr · 20.9 · 2.1 s |

*Credits per task · Intelligence Index · wait to the first answer, 2026-09-24. Minutes per task:
GPT-6 Luna 0.3 (low) to 5.7 (max), GPT-5.6 Luna 0.3 to 5.4.*

Every effort is cheap next to any tier — the whole scout load on GPT-6 Luna · Max is under 400
credits a month. What Max costs is nearly two minutes of silence per request. For a role you wait
on repeatedly, **GPT-6 Luna · High** (32.1, 3 credits, 7 s) is the sensible Luna; Max belongs to a
batch you do not sit and watch.

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
