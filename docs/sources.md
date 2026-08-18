# The three sources

What each one is, how it is read, and what it must never be used for.

## CursorBench — `https://cursor.com/cursorbench`

Cursor's own evaluation of agents on ambiguous, multi-file tasks from real sessions. The only
source that publishes an **end-to-end cost per task**, and the only one that separates a model
from its **effort** setting — which is why the whole page is organised around it.

Read from: the server-rendered leaderboard, as text. There is no API and no JSON payload in the
page; the rows are a CSS grid and arrive as run-together strings. Fields: rank, model, effort,
score %, $/task, tokens/task, steps/task, plus the benchmark version (3.2 as of 2026-08-18).

Moves on the scale of weeks — the page carries a changelog of re-runs (the most recent entries
re-priced Sonnet 5, Terra and Luna). Polled every 12 hours.

**Do not** compare a CursorBench score across effort levels without saying which effort: the same
model spans double-digit percentage points from low to max, and costs up to 20× more.

## AI Stupid Level — `https://aistupidlevel.info/`

Continuously re-benchmarks models and publishes a 0-100 score with a trend, a confidence interval
and a staleness flag. This is the drift signal: the answer to "Sonnet felt fine last week and feels
stupid today — is that me?".

Read from: the site's public JSON API (the backend is open source,
`StudioPlatforms/aistupidmeter-api`):

- `GET /api/dashboard/scores` — current score per model (`?period=`, `?sortBy=`)
- `GET /api/dashboard/history/{modelId}?period=7d` — that model's individual runs

Polled hourly; the run history is backfilled daily, which is what gives the sparklines a real week
of data on a fresh install.

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
comes from CursorBench, and the two only meet in the verdict cards.
