# The three sources

What each one is, how it is read, and what it must never be used for.

## Artificial Analysis — `https://artificialanalysis.ai/models`

Independent evaluation on their own hardware. For every model **at every effort setting** it
publishes the **Intelligence Index** (ten evaluations: AA-Briefcase, GDPval-AA, AutomationBench-AA,
Terminal-Bench 4.0, SciCode, Humanity's Last Exam, GDP-PDF, CritPt, AA-Omniscience and long-context
reasoning — v4.3 in September 2026), the **cost of one index task**, the output tokens it took, how
fast the model types and **how long you wait before the first answer token**. Quality, price and
time from the same runs — which is why this is the source the board is scored by, since
2026-09-22.

Read from: the page's **React Server Components payload** — the `self.__next_f.push([1, "…"])`
scripts Next.js streams every page with. The full table sits in it as plain JSON objects, one per
variant, each opening with its id and slug; the collector reassembles the stream, decodes those
objects with the standard library and ignores everything else. **Every model page carries every
model** (665 variants on 2026-09-22), so the URL is an entry point, not a subject — it is
`KVASIR_AA_URL`, because the page it names could be retired.

Three things that are *not* the data, and why the collector does not use them:

- The **schema.org `Dataset` blocks** (JSON-LD) carry only the top twenty of each chart. The old
  speed reader used them, which is why Sonnet 5, Terra and Sol "had no speed" in September.
- The `/data/*.txt` file the site's own charts load is **encrypted**. It is left alone.
- Their REST API needs a key, and was not needed.

This payload is an implementation detail of their site, not an API. The parser therefore refuses
a half-read page: fewer than `MIN_ROWS` variants or `MIN_PRICED` priced ones raises, the run log
records it, and the page keeps the last good reading.

What each field means, and how it is used:

| Field | Their words | Used as |
|---|---|---|
| `intelligenceIndex` | "Artificial Analysis Intelligence Index" | the score; decides the roles |
| `intelligenceIndexCostPerTask.cost.total` | "Weighted average cost (USD) per Intelligence Index task" | the price of a task; the credit budget |
| `timeToFirstAnswerToken.total` | "Seconds to first answer token received · Accounts for reasoning model 'thinking' time" | the wait; patience filters the loop roles by it |
| `timescaleData.medianOutputSpeed` | "Output tokens per second" | how fast it types; shown, never decides |
| `endToEndResponseTime.total` | "Seconds to output 500 tokens, including reasoning model 'thinking' time" | one exchange; shown |
| `terminalBench40` | Terminal-Bench 4.0 | a coding cross-check; shown, never decides |

**The unit is an Intelligence Index task**, a weighted average over ten evaluations — some of
them agentic and long, some a single hard question. It is not a CursorBench task, and credits per
task before and after 2026-09-22 are not the same measurement (see `docs/credits.md`).

**A new release is timed before it is priced.** GPT-6 Luna and GPT-6 Sol appeared on release day
with a score, a speed and token counts but no cost per task. Such a variant is on the board and
never in a role: a budget cannot be planned on no price, and estimating one from token counts
needs a cache-hit assumption that moves the answer by a factor of three. It joins the roles when
the price is published.

**Waiting is per effort; typing speed is not.** Reasoning effort *is* the waiting: Opus 5.5 answers
in 13 seconds at high and 170 at extra high. A variant without its own wait has no wait. Decode
rate belongs to the model and its hardware, so a variant that was not timed shows its family's,
labelled with the effort it came from. **Do not** write a rule that treats a missing measurement
as a slow model.

**Non-reasoning modes have no effort** and never reach the board — no number is shown without the
effort it was measured at. They are archived like everything else.

Polled every 12 hours. The Intelligence Index is versioned, and a new version is a re-baseline:
`db.benchmark_versions()` keeps the timeline and the page says so for six weeks after a change.

## AI Stupid Level — `https://aistupidlevel.info/`

Continuously re-benchmarks models and publishes a 0-100 score with a trend, a confidence interval
and a staleness flag. This is the drift signal: the answer to "Sonnet felt fine last week and feels
stupid today — is that me?".

Read from the site's JSON API. **In September 2026 it split in two**, which is worth knowing
before debugging a half-frozen drift section:

- `GET /api/v1/models` — current score per model. **Key-only** since 2026-09-04
  (`Authorization: Bearer asl_live_…`, free tier 10 calls a day, 1 a minute). The legacy
  `/api/dashboard/scores` now answers 401. Set `KVASIR_STUPIDLEVEL_API_KEY` and the collector uses
  v1; leave it empty and the scores freeze at the last good reading, with the page saying so.
- `GET /api/dashboard/history/{modelId}?period=7d` — that model's individual runs. Still open, no
  key, and still current; this is what draws the sparklines, Δ7d and min–max.

Scores are polled every 4 hours (the free quota is 10 a day); the run history every 6 hours. Both
cadences are environment variables.

**Do not** plot the dashboard score and the run history as one line. The dashboard number is a
smoothed conversion of the runs; they are stored as separate series for that reason. **Do not**
present these scores as effort-specific — the source does not publish the effort it used.

## GitHub Copilot — `https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing`

The billing reference for Copilot's AI credits: every model available, its release status, its
category (Lightweight / Versatile / Powerful) and its price per million tokens, split into input,
cached input, cache write and output. This is the availability filter — a model that wins every
benchmark is irrelevant if it is not on the company's list — and the budget number.

Read from: the page's real `<table>` markup, by column *name* (vendors' tables differ: some carry
Tier/Threshold, some carry Cache write). Long-context tiers are kept as separate rows and the
default tier is the one the verdict prices against. Polled every 12 hours.

**Do not** treat a Copilot price as a per-task cost. It is per million tokens; the per-task figure
comes from Artificial Analysis, and the two only meet in the verdict cards.

## Retired: CursorBench — `https://cursor.com/cursorbench`

Scored the board from 2026-08-18 to 2026-09-22: Cursor's own evaluation of agents on ambiguous,
multi-file tasks, with cost, tokens and steps per task at every effort. Replaced by Artificial
Analysis, which publishes the same per-effort cost and score for far more models and adds the
wait. Its snapshots stay in the archive and readable through `/api/history?source=cursorbench`,
as do those of the JSON-LD speed reader (`source=speed`). Its 3.2 → 4.0 re-baseline on 2026-09-10
is why the benchmark-version timeline exists.
