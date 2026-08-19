"""Runtime configuration — every knob is an environment variable with a sane default.

Kvasir runs as a single container on Unraid; there is no config file to mount and
no secrets to manage. Everything below is safe to expose in the UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _tiers(name: str, default: str) -> list[dict]:
    """"Basic:13000,Heavy:100000" -> the AI-credit tiers this page reports on.

    Tiers are an organisation's own allocation of Copilot AI credits, not a GitHub product,
    so they belong in configuration rather than in the code.
    """
    out = []
    for part in _csv(name, default):
        label, _, credits = part.partition(":")
        try:
            amount = int(credits)
        except ValueError:
            continue
        out.append({"id": label.strip().lower(), "name": label.strip(), "credits": amount})
    return out


def _csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    data_dir: str = os.environ.get("KVASIR_DATA_DIR", "/data")
    port: int = _int("KVASIR_PORT", 8688)

    # Poll intervals, in minutes. AI Stupid Level re-scores hourly; the other two
    # are documentation-shaped and move on the scale of days.
    interval_stupidlevel: int = _int("KVASIR_INTERVAL_STUPIDLEVEL", 60)
    interval_cursorbench: int = _int("KVASIR_INTERVAL_CURSORBENCH", 720)
    interval_copilot: int = _int("KVASIR_INTERVAL_COPILOT", 720)

    # Fetch every model the sources publish (the archive keeps everything), but hide
    # these from the default view. The UI has a switch to show them anyway.
    hidden_models: list[str] = field(
        default_factory=lambda: _csv(
            "KVASIR_HIDDEN_MODELS",
            "grok-4.5,grok-4.6,fable-5,gpt-5.6-sol,kimi-k3,kimi-k2.7-code,glm-5.2",
        )
    )

    # Monthly AI-credit allocations we report on, and the one selected when a visitor has
    # never picked. 1 credit = $0.01, so 13000 credits is a $130 month.
    tiers: list[dict] = field(
        default_factory=lambda: _tiers("KVASIR_TIERS", "Basic:13000,Heavy:100000,Power:200000")
    )
    default_tier: str = os.environ.get("KVASIR_DEFAULT_TIER", "heavy")

    # Tier thresholds, in USD per CursorBench task. Shown in the UI next to the verdict.
    worker_max_cost_usd: float = float(os.environ.get("KVASIR_WORKER_MAX_COST", "2.50"))
    scout_max_cost_usd: float = float(os.environ.get("KVASIR_SCOUT_MAX_COST", "0.60"))
    architect_score_slack_pp: float = float(os.environ.get("KVASIR_ARCHITECT_SLACK", "3.0"))

    request_timeout_s: int = _int("KVASIR_REQUEST_TIMEOUT", 30)
    # Set to 0 to serve whatever is already archived and never touch the network — used by
    # the tests, and handy when developing on a train.
    autostart: bool = _int("KVASIR_AUTOSTART", 1) == 1
    user_agent: str = os.environ.get(
        "KVASIR_USER_AGENT",
        "kvasir/1.0 (+https://github.com/morphem/kvasir) personal dashboard collector",
    )

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "kvasir.db")


settings = Settings()
