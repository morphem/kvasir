"""Canonical model keys and effort levels.

The three sources spell the same model three ways: CursorBench says "Opus 5 Extra High",
AI Stupid Level says "claude-opus-5", GitHub's docs say "Claude Opus 5". Everything is
folded into one key ("opus-5") plus a separate effort level, because the join between the
sources is the whole point of this page.

Normalisation is rule-based, not a lookup table, so a model released next month lands in
the right bucket without a code change. ALIASES only carries the cases the rules cannot
reach.
"""

from __future__ import annotations

import re

# Effort as the sources spell it -> our canonical ladder. "default" means the source
# published no effort at all; we never silently invent one, because a benchmark number
# without its effort setting is not comparable.
EFFORTS = ["low", "medium", "high", "xhigh", "max", "default"]

EFFORT_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra High",
    "max": "Max",
    "default": "—",
}

_EFFORT_SUFFIXES = [
    ("extra high", "xhigh"),
    ("very high", "xhigh"),
    ("xhigh", "xhigh"),
    ("max", "max"),
    ("high", "high"),
    ("medium", "medium"),
    ("low", "low"),
    ("minimal", "low"),
    ("none", "default"),
]

# Vendor prefixes that carry no information once the key is canonical.
_STRIP_PREFIXES = ("claude ", "claude-", "google ", "openai ", "anthropic ", "xai ", "x-ai ")

ALIASES = {
    "gemini-3.1-pro-preview": "gemini-3.1-pro",
    "opus-4.8-fast-mode": "opus-4.8-fast",
}

VENDOR_BY_PREFIX = (
    ("opus", "anthropic"),
    ("sonnet", "anthropic"),
    ("haiku", "anthropic"),
    ("fable", "anthropic"),
    ("gpt", "openai"),
    ("o3", "openai"),
    ("gemini", "google"),
    ("grok", "xai"),
    ("kimi", "moonshot"),
    ("glm", "zhipu"),
    ("deepseek", "deepseek"),
    ("composer", "cursor"),
    ("mai-", "microsoft"),
    ("raptor", "microsoft"),
)


def split_effort(name: str) -> tuple[str, str]:
    """Split "Opus 5 Extra High" into ("Opus 5", "xhigh").

    Only a trailing effort word counts — "GPT-5.6 Terra High" is Terra at high effort,
    while "Gemini 3.7 Flash" keeps "Flash" as part of the model name.
    """
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    low = cleaned.lower()
    for suffix, effort in _EFFORT_SUFFIXES:
        if low.endswith(" " + suffix):
            return cleaned[: -(len(suffix) + 1)].strip(), effort
    return cleaned, "default"


def model_key(name: str) -> str:
    """Fold any spelling of a model name into one lowercase key."""
    key = re.sub(r"\s+", " ", (name or "").strip()).lower()
    key = key.replace("(preview)", "").replace("(fast mode)", "fast mode").strip()
    for prefix in _STRIP_PREFIXES:
        if key.startswith(prefix):
            key = key[len(prefix) :]
            break
    key = re.sub(r"[\s_]+", "-", key)
    key = re.sub(r"-+", "-", key).strip("-")
    # API names carry a release date ("claude-sonnet-4-5-20250929"); the docs do not.
    key = re.sub(r"-\d{6,8}$", "", key)
    # "opus-4-8" and "opus-4.8" are the same model spelled by different sources.
    key = re.sub(r"(?<=\d)-(?=\d)", ".", key)
    return ALIASES.get(key, key)


def vendor_of(key: str) -> str:
    for prefix, vendor in VENDOR_BY_PREFIX:
        if key.startswith(prefix):
            return vendor
    return "other"


def display_name(key: str) -> str:
    """Human label for a canonical key: "gpt-5.6-terra" -> "GPT-5.6 Terra"."""
    words = key.split("-")
    out = []
    for i, word in enumerate(words):
        if word in {"gpt", "glm", "mai"}:
            out.append(word.upper())
        else:
            out.append(word[:1].upper() + word[1:])
    # The vendor prefix binds to the version number: "GPT-5.6", not "GPT 5.6".
    if len(out) > 1 and out[0] == "GPT":
        out = [f"{out[0]}-{out[1]}"] + out[2:]
    return " ".join(out)


def label(key: str, effort: str) -> str:
    """The one string the UI shows — a model is never named without its effort."""
    suffix = EFFORT_LABELS.get(effort, effort)
    return f"{display_name(key)} · {suffix}" if effort != "default" else display_name(key)
