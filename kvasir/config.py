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


def _secret(name: str, data_dir: str) -> str:
    """A secret, from the environment or from the data volume — in that order.

    The volume is the only thing that survives every way this container gets recreated: the
    Unraid template, the Docker tab's Apply button, and the deploy script all build the run
    command differently, and an environment variable set by one of them is simply absent in
    the others. That is how the key installed on 8 September was gone by the 12th, with the
    file still sitting on disk. A secret that lives beside the state it belongs to cannot be
    lost by a redeploy.

    Accepts either a bare key on one line, or KEY=value lines.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for filename in (f"{name.lower().replace('kvasir_', '')}.key", "secrets.env"):
        try:
            with open(os.path.join(data_dir, filename), encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        return line
                    field_name, _, field_value = line.partition("=")
                    if field_name.strip() == name:
                        return field_value.strip().strip("\"'")
        except OSError:
            continue
    return ""


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
    # move with model releases, on the scale of days.
    # Hourly until the source went key-only; the free tier now allows 10 requests a day, so
    # six-a-day leaves room for retries. Lower it if a paid key ever arrives.
    interval_stupidlevel: int = _int("KVASIR_INTERVAL_STUPIDLEVEL", 240)
    # Artificial Analysis re-runs a model when it ships, and prices a new release some hours or
    # days after timing it. Every three hours puts a newly priced model on the board the same
    # morning rather than up to half a day late, and is still only eight page reads a day.
    interval_aa: int = _int("KVASIR_INTERVAL_AA", 180)
    interval_copilot: int = _int("KVASIR_INTERVAL_COPILOT", 720)
    # AI Stupid Level's published run history, which draws the sparklines. Daily was too
    # slow: the headline score moves hourly, so the chart beside it was up to a day behind.
    interval_backfill: int = _int("KVASIR_INTERVAL_BACKFILL", 360)

    # Models GitHub sells but our own Copilot subscription does not enable. Everything else
    # is decided from data: a model absent from GitHub's pricing page is not ours to pick,
    # so it never needs an entry here.
    #
    # Entries are families, not exact keys. "fable" blocks fable-5 and fable-5.1 — an exact
    # key list let fable-5.1 into the verdict the day GitHub shipped it.
    disabled_models: list[str] = field(
        default_factory=lambda: _csv(
            "KVASIR_DISABLED_MODELS",
            os.environ.get("KVASIR_HIDDEN_MODELS", "grok,fable,kimi-k2.7,gpt-6-astra"),
        )
    )

    # The organisation's AI-credit allocations, and the one selected when a visitor has never
    # picked. 1 credit = $0.01, so 13000 credits is a $130 month.
    tiers: list[dict] = field(
        default_factory=lambda: _tiers("KVASIR_TIERS", "Basic:13000,Heavy:100000,Power:200000")
    )
    default_tier: str = os.environ.get("KVASIR_DEFAULT_TIER", "heavy")
    # How long a loop role may keep you waiting, when a visitor has never picked: one of the
    # names in budget.PATIENCE (fast, balanced, any).
    default_patience: str = os.environ.get("KVASIR_DEFAULT_PATIENCE", "balanced")

    # AI Stupid Level closed its scores endpoint behind a key in September 2026. Without
    # one the page keeps the last good scores and says how old they are; with one it polls
    # the v1 API. The free tier allows 10 requests a day, which is why the interval above
    # is hours rather than minutes.
    stupidlevel_api_key: str = field(
        default_factory=lambda: _secret(
            "KVASIR_STUPIDLEVEL_API_KEY", os.environ.get("KVASIR_DATA_DIR", "/data")
        )
    )

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
