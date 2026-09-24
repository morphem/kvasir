# Kvasir

**Which agent do I start for this task, today?**

Built for internal use inside one organisation, where the model list is whatever its GitHub Copilot
subscription enables and the budget is an AI-credit tier. Hosted on a personal domain so it is one
link away; it carries no company data — every number comes from three public sources.

One page that merges three sources into one answer, and keeps the history behind it:

| Source | What it contributes |
|---|---|
| [Artificial Analysis](https://artificialanalysis.ai/models) | Intelligence Index, cost per task and time per task — **always per effort level**, all from the same runs |
| [AI Stupid Level](https://aistupidlevel.info/) | Drift: whether a model is quietly getting worse under the same name |
| [GitHub Copilot docs](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing) | What our Copilot enables, and what a million tokens costs |

Three roles come out of it — **architect** (plans and decomposes), **worker** (does the typical
job), **scout** (cheap and mechanical) — each filled by whichever model wins on today's data, not
by a hard-coded list. The page also shows the *distance* between the roles, because the useful
question is rarely "which is best" but "is the upgrade worth it here": sometimes a slightly dearer
model costs pennies more and is far better, sometimes it costs five times more for half a point.

On top of that sits the **AI-credit layer**: pick your Copilot credit tier (Basic / Heavy / Power)
and the whole page re-answers for that monthly budget — which model each role can afford, what a
month of ordinary work costs in credits, and how much headroom is left. The rate it converts with
(1 AI credit = $0.01) is read out of GitHub's own pricing page rather than hardcoded. See
[`docs/credits.md`](docs/credits.md) for the verified quotes, the workload model, and what each
tier turns out to afford.

The second switch is **patience**: how long one task may take on the worker and the scout (Fast,
Balanced, Any). Those are the roles you iterate with — prompt, read, correct, prompt again — so one
slow loop makes the whole session slow; the same model can finish a task in a minute at one effort
and seven at another. The architect plans once and is never on that clock.

The first tab is the **map**: intelligence against cost per task, time per task and output tokens
per task, drawn the way Artificial Analysis draws them — a split in each axis, the top-left quadrant
marked as the place to shop, the Pareto line through what nothing beats. Links can name a chart
(`?map=time`) and draw the rest of the market behind our board for scale (`&market=1`).

Every reading is archived in SQLite, deduplicated by content hash, so the page behaves like a
weather report while the database keeps the climate record.

## Run it

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/uvicorn kvasir.api:app --port 8688     # http://127.0.0.1:8688
.venv/bin/pytest -q
```

Docker:

```bash
docker run -d --name kvasir -p 8688:8688 -v /mnt/user/appdata/kvasir:/data \
  ghcr.io/morphem/kvasir:latest
```

On Unraid, copy `unraid/my-Kvasir.xml` into `/boot/config/plugins/dockerMan/templates-user/` and
add the container from the template — updates then arrive the normal Unraid way. See
[`docs/deploy.md`](docs/deploy.md).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `KVASIR_DATA_DIR` | `/data` | Where the SQLite archive lives |
| `KVASIR_INTERVAL_STUPIDLEVEL` | `240` | Drift poll interval, minutes. The free API tier allows 10 calls a day |
| `KVASIR_INTERVAL_AA` | `180` | Artificial Analysis poll interval, minutes |
| `KVASIR_AA_URL` | `…/models/claude-opus-5-5` | The Artificial Analysis page the board is read from. Every model page carries every model; this is only an entry point |
| `KVASIR_INTERVAL_COPILOT` | `720` | Copilot pricing poll interval, minutes |
| `KVASIR_STUPIDLEVEL_API_KEY` | *(empty)* | Free key from aistupidlevel.info. Falls back to `secrets.env` or `stupidlevel_api_key.key` inside the data volume, which is what survives a container rebuild. Without a key the drift scores freeze at the last good reading |
| `KVASIR_DISABLED_MODELS` | `grok,fable,kimi-k2.7,gpt-6-astra` | Model *families* Copilot sells but we cannot use. Models absent from Copilot are excluded automatically |
| `KVASIR_AUTOSTART` | `1` | `0` serves the archive and never touches the network |
| `KVASIR_TIERS` | `Basic:13000,Heavy:100000,Power:200000` | AI-credit tiers to report on, `Name:credits` |
| `KVASIR_DEFAULT_TIER` | `heavy` | Tier shown to a visitor who has never picked one |
| `KVASIR_DEFAULT_PATIENCE` | `balanced` | Patience shown to a visitor who has never picked one: `fast`, `balanced` or `any` |

## API

| Endpoint | Returns |
|---|---|
| `GET /api/view` | Everything the page renders, in one consistent reading (`?all=1` unhides models) |
| `GET /api/health` | Per-source freshness and failure counts |
| `GET /api/history?source=&model=&effort=&days=` | Archived readings for one model (retired sources `cursorbench` and `speed` stay readable) |
| `GET /api/drift/{model_key}?days=` | Drift series (`aisl-run` by default) |
| `GET /api/changelog` | Every release, newest first — what the "What's new" window shows |
| `POST /api/refresh` | Force a collection round now |

Krzysztof Prawdzik · BlinkNeuron
