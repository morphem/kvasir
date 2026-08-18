# CLAUDE.md — working agreement for Kvasir

**Kvasir** is one page that answers a single question: *which agent do I start for this task,
today.* It merges three sources — **CursorBench** (cost, tokens and steps per task, always per
effort level), **AI Stupid Level** (drift: is this model quietly getting worse) and **GitHub
Copilot's models-and-pricing docs** (what we can actually pick at work, and what it bills) — into
three roles: architect, worker, scout. Python + FastAPI + SQLite in a single container on Unraid,
served at `kvasir.blinkneuron.eu`. State is a SQLite archive under `/data`; there is no other
persistence and no external database. Code, comments, docs and commits in English; the UI and
conversation with the owner in Polish.

Infra conventions (Unraid, appdata layout, SWAG, deploy doctrine) are owned by
`homelab/CLAUDE.md` and `xreal/CONSTITUTION.md`. This repo does not restate them.

## The one invariant that must never break

**No number is ever shown without the effort it was measured at, and no half-read source is ever
shown as data.** A benchmark score without its effort setting is not comparable to anything, and a
parser that returns 3 of 56 rows because a page changed shape would quietly turn this page into
confident nonsense. Both halves are pinned by tests: `test_every_tier_gets_a_pick_with_an_effort`
and `test_cursorbench_refuses_a_half_read_page` (plus the `MIN_ROWS` guard in every collector).
When a source breaks, the run log records the failure, the page keeps showing the last good
reading with its real age, and the freshness chip goes amber. Never "fix" a parser by relaxing
`MIN_ROWS`.

## Domain notes that bite

- **Money is integer micro-dollars** (`*_uusd`), never floats — same reason the ecosystem keeps PLN
  in grosze. Prices are per 1M tokens (Copilot) or per benchmark task (CursorBench); both get
  summed and diffed across months of snapshots. Convert at the edge, in `_usd()`.
- **The three sources spell every model differently** — `Opus 5 Extra High` / `claude-opus-5` /
  `Claude Opus 5`. `naming.py` folds all of them into one key plus a separate effort, by rule, not
  by lookup table. A new model must land correctly without a code change; add to `ALIASES` only
  what the rules genuinely cannot reach.
- **CursorBench's leaderboard has no markup to hang on.** Rows arrive as one run-together string
  (`9Opus 5 High66.7%$3.9127,93248`). The score regex is bounded to `0.0-100.0` on purpose:
  model names end in digits too, and an unbounded number reads "Composer 2." + "556.1%" out of the
  same line. That exact case is a test.
- **AI Stupid Level publishes no effort per score.** Those runs use each provider's default, so the
  UI says so rather than implying the numbers are comparable to CursorBench's per-effort rows. Its
  dashboard score and its per-run history are *different measurements* — they are stored in
  separate series (`aisl-dashboard`, `aisl-run`) and must not be plotted as one line.
- **Deduplication is by content hash.** Polling hourly writes a snapshot only when something moved,
  so the archive is a change log, not 168 copies of Tuesday. `source_run` still records every poll,
  including the failures — that is the honesty log.
- **Hidden models are hidden, never dropped.** `KVASIR_HIDDEN_MODELS` filters the default view;
  collection and archiving always cover everything the sources publish. `/api/view?all=1` shows
  them.

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
| `kvasir/recommend.py` | The verdict: tiers, the cost/quality frontier, the gaps between roles, the drift veto. Every threshold is echoed into the API response. |
| `kvasir/catalog.py` | The task list and the three roles — Polish UI copy, English keys. |
| `kvasir/api.py` | One payload (`/api/view`) for the whole page, plus `/api/history` and `/api/drift` over the archive. |
| `web/` | The page: `index.html` skeleton, `app.js` rendering, `style.css` in BlinkNeuron colours (cyan = it fits, violet = it is a gap — semantic, never decorative). |
