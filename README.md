# Kvasir

**Which agent do I start for this task, today?**

Built for internal use inside one organisation, where the model list is whatever its GitHub Copilot
subscription enables and the budget is an AI-credit tier. Hosted on a personal domain so it is one
link away; it carries no company data — every number comes from three public sources.

One page that merges three sources into one answer, and keeps the history behind it:

| Source | What it contributes |
|---|---|
| [CursorBench](https://cursor.com/cursorbench) | Cost, tokens and steps per real task — **always per effort level** |
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
| `KVASIR_INTERVAL_STUPIDLEVEL` | `60` | Drift poll interval, minutes |
| `KVASIR_INTERVAL_CURSORBENCH` | `720` | CursorBench poll interval, minutes |
| `KVASIR_INTERVAL_COPILOT` | `720` | Copilot pricing poll interval, minutes |
| `KVASIR_HIDDEN_MODELS` | see `config.py` | Hidden from the default view — still collected and archived |
| `KVASIR_WORKER_MAX_COST` | `2.50` | Worker's cost ceiling, USD per task |
| `KVASIR_SCOUT_MAX_COST` | `0.60` | Scout's cost ceiling, USD per task |
| `KVASIR_AUTOSTART` | `1` | `0` serves the archive and never touches the network |
| `KVASIR_TIERS` | `Basic:13000,Heavy:100000,Power:200000` | AI-credit tiers to report on, `Name:credits` |
| `KVASIR_DEFAULT_TIER` | `heavy` | Tier shown to a visitor who has never picked one |

## API

| Endpoint | Returns |
|---|---|
| `GET /api/view` | Everything the page renders, in one consistent reading (`?all=1` unhides models) |
| `GET /api/health` | Per-source freshness and failure counts |
| `GET /api/history?source=&model=&effort=&days=` | Archived readings for one model |
| `GET /api/drift/{model_key}?days=` | Drift series (`aisl-run` by default) |
| `POST /api/refresh` | Force a collection round now |

Krzysztof Prawdzik · BlinkNeuron
