# CLAUDE.md — working agreement for Kvasir

**Kvasir** is one page that answers a single question: *which agent do I start for this task,
today.* It merges three sources — **Artificial Analysis** (Intelligence Index, cost per task and
time per task, always per effort level, all from the same runs), **AI Stupid Level**
(drift: is this model quietly getting worse) and **GitHub Copilot's models-and-pricing docs** (what
we can actually pick at work, and what it bills) — into three roles: architect, worker, scout,
filled per AI-credit tier and per patience setting. CursorBench scored the board until
2026-09-22; its archive stays readable. Python + FastAPI + SQLite in a single container on Unraid,
served at `kvasir.blinkneuron.eu`. State is a SQLite archive under `/data`; there is no other
persistence and no external database. **Everything shipped is English — code, comments, docs,
commits and the page itself.** This is a deliberate, owner-approved exception to the ecosystem
rule that UI copy is Polish (`xreal/CONSTITUTION.md` §1): the page is shared with colleagues and
every source it quotes is English, so a Polish shell around English data would only add a
translation layer to maintain. Conversation with the owner stays Polish.

**Audience: one organisation, internally — and the page never names it.** The model board is
limited to what that organisation can actually start — sold by Copilot, and not in a disabled
family (`KVASIR_DISABLED_MODELS`) — and the budget layer works in its AI-credit tiers — Basic 13K,
Heavy 100K, Power 200K. Employer, client and project names stay off the page and out of this repo:
it is publicly reachable, so everything here has to be something three public sources already say.
Company data, code and account details never appear, and must not start to.

Infra conventions (Unraid, appdata layout, SWAG, deploy doctrine) are owned by
`homelab/CLAUDE.md` and `xreal/CONSTITUTION.md`. This repo does not restate them.

## The one invariant that must never break

**No number is ever shown without the effort it was measured at, and no half-read source is ever
shown as data.** A benchmark score without its effort setting is not comparable to anything, and a
parser that returns 3 of 56 rows because a page changed shape would quietly turn this page into
confident nonsense. Both halves are pinned by tests: `test_every_tier_gets_a_pick_with_an_effort`
and `test_artificialanalysis_refuses_a_half_read_page` (plus the `MIN_ROWS` guard in every
collector, and `MIN_PRICED` in the Artificial Analysis one).
When a source breaks, the run log records the failure, the page keeps showing the last good
reading with its real age, and the freshness chip goes amber. Never "fix" a parser by relaxing
`MIN_ROWS`.

## Domain notes that bite

- **Money is integer micro-dollars** (`*_uusd`), never floats — same reason the ecosystem keeps PLN
  in grosze. Prices are per 1M tokens (Copilot) or per index task (Artificial Analysis); both get
  summed and diffed across months of snapshots. Convert at the edge, in `_usd()`.
- **The three sources spell every model differently** — `Claude Opus 5 (Adaptive Reasoning, Max
  Effort)` / `claude-opus-5` / `Claude Opus 5`, and older AA names put the version first (`Claude
  4.5 Haiku`). `naming.py` folds all of them into one key plus a separate effort, by rule, not
  by lookup table. A new model must land correctly without a code change; add to `ALIASES` only
  what the rules genuinely cannot reach.
- **Artificial Analysis is read from its RSC payload, not its JSON-LD.** The schema.org blocks
  carry only the top twenty of each chart; the `self.__next_f.push` stream on any model page
  carries all ~665 variants as plain JSON objects. That stream is their implementation detail, not
  an API — hence `MIN_ROWS`/`MIN_PRICED`. Their `/data/*.txt` chart file is encrypted: leave it
  alone. Read the record's `release.name` for the model and `effort.slug` for the effort; a
  non-reasoning mode gets no effort and never reaches the board.
- **A release is timed before it is priced.** GPT-6 Luna and Sol arrived scored and timed but with
  no cost per task. `cost_uusd` stays `None`, the candidate is `priced: false`, and it is shown but
  never planned. Never estimate the price from token counts — the cache-hit share alone moves it 3×.
- **AI Stupid Level publishes no effort per score.** Those runs use each provider's default, so the
  UI says so rather than implying the numbers are comparable to Artificial Analysis's per-effort
  rows. Its
  dashboard score and its per-run history are *different measurements* — they are stored in
  separate series (`aisl-dashboard`, `aisl-run`) and must not be plotted as one line.
- **Deduplication is by content hash.** Polling hourly writes a snapshot only when something moved,
  so the archive is a change log, not 168 copies of Tuesday. `source_run` still records every poll,
  including the failures — that is the honesty log.
- **The AI-credit rate is a quoted fact, not a constant.** GitHub's pricing page says "1 AI credit
  = $0.01 USD"; the collector parses that sentence into snapshot metadata and the whole tier layer
  (`kvasir/budget.py`) divides by it. Never replace it with a literal — if the sentence stops
  parsing, the page must say the rate is assumed. `docs/credits.md` holds the quotes and the
  workload model.
- **Snapshot dedup is on rows, so metadata is refreshed in place.** An unchanged reading writes no
  new snapshot, but `db.archive` updates `meta_json` — otherwise a fact the parser only learned to
  extract today would never reach the database, because the numbers had not moved.
- **The workload model is published with its answer.** Days, tasks per day, role mix, overhead and
  the budget split are constants at the top of `budget.py` and are printed on the page. Re-tuning
  them until the answer looks better is falsifying the answer; replace the model with measured
  usage instead.
- **Availability is derived, not listed.** A model reaches the verdict only if GitHub's Copilot
  pricing page sells it *and* it is not in a disabled family. That first half is data: benchmark-only
  models (Composer, Muse Spark) fall off the board with nobody maintaining anything. Never
  reintroduce a hand-kept "available models" list — the one we had recommended Muse Spark, which
  Copilot does not carry.
- **`KVASIR_DISABLED_MODELS` holds families, not keys.** "fable" covers fable-5 *and* fable-5.1.
  The exact-key list it replaced let fable-5.1 become the recommended architect the day GitHub
  shipped it, because "fable-5" did not match it. Point releases arrive faster than lists get
  updated; match families.
- **Secrets live in the data volume, not only in an environment variable.** `_secret()` reads
  `KVASIR_STUPIDLEVEL_API_KEY`, then `secrets.env` / `*.key` under `/data`. The Unraid template,
  the Docker tab's Apply button and `deploy/install-unraid.sh` each build the run command
  differently, so a variable set by one is absent in the others: the key installed on 8 September
  was gone by the 12th, with the file still on disk. The volume is the only thing every path
  keeps. The file must be readable by 99:100 — the container is not root.
- **A benchmark can re-baseline under you.** CursorBench 4.0 (2026-09-10) replaced 3.2, dropped the
  top score 19 points and re-ran a third of the models; the Intelligence Index is versioned the
  same way (v4.3 in September 2026), and switching sources on 2026-09-22 changed the unit again. `db.benchmark_versions()` keeps that
  timeline, `/api/history` tags every reading with the version that produced it, and the page says
  so for six weeks after a change. Never compare scores across versions, and never explain a
  shrunken board as a bug before checking the version.
- **Clocks, joined differently.** Output speed is a property of the model and its hardware, so a
  variant that was not timed borrows its family's, labelled with the effort it came from; time per
  task and the wait to the first answer are not, because reasoning effort *is* the time (Opus 5.5:
  1.3 min a task at low, 7.5 at xhigh). The only exception is the labelled lower-bound floor.
  `_speed_block()` keeps them apart on purpose. A zero means absent, never instant.
- **Patience is a ceiling for the loop roles, never a score.** The worker and the scout are the
  roles you iterate with, so a variant whose time per task (AA's decode time per index task,
  reasoning included — every priced variant has one) passes the selected ceiling
  (`budget.PATIENCE`: Fast 3/1.5 min, Balanced 6/3, Any) cannot hold one; the architect is exempt,
  because a plan is made once and deliberately. It replaced first an 80 tok/s floor, which barred
  whole models once the source timed everything, then the wait to the first answer, which says
  when a loop starts rather than how long it lasts. A variant nobody timed passes — absence of
  evidence decides nothing — *unless a lower effort of the same model was timed*: then it takes at
  least that long (`recommend._task_floor`). Without that floor Opus 5.5 · Max, the slowest variant
  on the board, took a Fast worker's seat as "unmeasured". The loop roles climb a frontier
  *rebuilt* from the quick variants, not the full frontier filtered — a slow rung can hide the
  quick variant it dominated. The opening picks keep the stack's shape too: a scout never opens
  dearer than its worker.
- **The map splits each axis in the middle, and each x half has its own scale.** Cost splits at
  $1, time at the worker's patience limit, tokens at the geometric middle; y at the middle of the
  range, as on AA's own charts. A fixed split otherwise lands wherever the data puts it (75% of
  the width for cost, 30% for time) and the attractive quadrant becomes a sliver. Ordering is never
  changed, and the subtitle says the halves are scaled apart. Points estimated from a floor are
  drawn hollow and kept off the Pareto line.
- **An allowance is spent, not hoarded — but never silently.** Unused credits pool back to the
  billing entity, so the plan buys up to `TARGET_UTILISATION` and stops at `MAX_UTILISATION`.
  Surplus goes in role order (architect first); a role may not climb onto another role's exact
  variant, and a lower role may not score more *or cost more per task* than the role above it (at
  Heavy/Fast the quick frontier once put Opus 5 · Medium on the scout at 219 credits under a 182-credit
  worker). One model at three efforts is allowed — on the September data Opus 5.5 leads at every
  price from $0.55 up, and effort is the dial between the roles. When the plan stops short it records `stopped_because`: an unspent tier is either a
  finding or a fault, and the difference is the reason printed next to it.
- **Every deploy a user can see adds a changelog entry — that is the version bump.**
  `kvasir/changelog.py` is the single source: `VERSION` is its newest entry, `/api/changelog`
  serves it, and the page compares it with the last version the browser showed
  (`localStorage["kvasir.seen"]`) to open "What's new" once for a returning visitor. No entry, no
  popup — so write one for anything that changes what the page shows or says, in English, for the
  people who use the page, with `where` pointing at the tab (and map chart) it lives on. Internals
  stay in the commit log. A first visit records the version silently; a visitor from before the
  changelog existed sees the last two weeks.
- **Excluded models are excluded, never dropped.** Collection and archiving always cover everything
  the sources publish; `/api/view?all=1` opens the board so the cost of the restriction is visible.

## Behavioural guidelines (Andrej Karpathy skills)

1. **Think before coding** — state assumptions; surface interpretations; ask when a significant
   call is ambiguous rather than guessing.
2. **Simplicity first** — minimum code that solves the problem. No framework on the front end, no
   chart library, no ORM, no scheduler dependency: one asyncio loop, stdlib HTML parsing, inline
   SVG.
3. **Surgical changes** — touch only what the task needs; match existing style.
4. **Goal-driven execution** — "the container is up" is not done. Done is: the public URL answers,
   the three freshness chips are green, and the verdict names a model *with its effort*.

## Repo commands

```bash
uv venv && uv pip install -e ".[dev]"          # install
.venv/bin/uvicorn kvasir.api:app --port 8688 --reload   # dev server -> http://127.0.0.1:8688
KVASIR_AUTOSTART=0 .venv/bin/uvicorn kvasir.api:app     # dev without touching the network
.venv/bin/pytest -q                            # tests (no network, fixtures in tests/fixtures)
docker build -t kvasir . && docker run -p 8688:8688 -v $PWD/data:/data kvasir
./deploy/install-unraid.sh --template          # ship it to the box
```

## Architecture in one breath

| File | Responsibility |
|---|---|
| `kvasir/collectors/*.py` | One module per source: `parse()` is pure (tested against saved fixtures), `fetch()` is the network wrapper. |
| `kvasir/htmlparse.py` | Stdlib table + text readers, and `usd_to_uusd()` — the money boundary. |
| `kvasir/naming.py` | Canonical model keys and the effort ladder. The join between the three sources lives here. |
| `kvasir/db.py` | The archive: snapshots, observations, run log, drift series. Content-hash dedup. |
| `kvasir/collect.py` · `scheduler.py` | Poll, archive, log; one loop that asks each source "are you due?" from the database, so a restart never loses the schedule. |
| `kvasir/recommend.py` | The board: joins the three sources, availability, the value ladder, the gaps between roles, the drift-freshness check, and the archived decision. |
| `kvasir/budget.py` | The roles: one plan per tier × patience — shares, ladder walks, drift veto, patience, surplus walk, stop reasons. Every constant is echoed into the API response. |
| `kvasir/catalog.py` | The task list and the three roles — English copy, see the language note above. |
| `kvasir/api.py` | One payload (`/api/view`) for the whole page, plus `/api/history` and `/api/drift` over the archive, and `/api/changelog`. |
| `kvasir/changelog.py` | What changed, release by release, in the page's words — and the app's version. |
| `web/` | The page: `index.html` skeleton, `app.js` rendering, `style.css` in BlinkNeuron colours (cyan = it fits, violet = it is a gap — semantic, never decorative). Two faces, dark and light, switched the blinkneuron.eu way (`bn.theme`, `data-theme`, system preference until chosen, applied before first paint). Every colour is a token on `:root` — never a hex literal in `app.js`, where it would stay dark on white; SVG takes tokens through `style=""`, since presentation attributes cannot hold `var()`. |
