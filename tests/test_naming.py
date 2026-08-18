"""The join between the three sources is name normalisation; if it slips, the page lies."""

import pytest

from kvasir.naming import label, model_key, split_effort, vendor_of


@pytest.mark.parametrize(
    "raw,expected_key,expected_effort",
    [
        ("Opus 5 Extra High", "opus-5", "xhigh"),
        ("Opus 5 Max", "opus-5", "max"),
        ("GPT-5.6 Terra High", "gpt-5.6-terra", "high"),
        ("Gemini 3.7 Flash", "gemini-3.7-flash", "default"),
        ("Gemini 3.7 Flash Low", "gemini-3.7-flash", "low"),
        ("Composer 2.5", "composer-2.5", "default"),
        ("Kimi K2.7 Code", "kimi-k2.7-code", "default"),
        # the three spellings of one model, from the three sources
        ("Claude Sonnet 4.6", "sonnet-4.6", "default"),
        ("claude-sonnet-4-6", "sonnet-4.6", "default"),
        ("Sonnet 4.6 Medium", "sonnet-4.6", "medium"),
        # API names carry a release date, docs names do not
        ("claude-sonnet-4-5-20250929", "sonnet-4.5", "default"),
        ("Claude Opus 4.5", "opus-4.5", "default"),
    ],
)
def test_split_and_key(raw, expected_key, expected_effort):
    base, effort = split_effort(raw)
    assert model_key(base) == expected_key
    assert effort == expected_effort


def test_vendor_and_label():
    assert vendor_of("opus-5") == "anthropic"
    assert vendor_of("gpt-5.6-luna") == "openai"
    assert vendor_of("composer-2.5") == "cursor"
    # A model is never named without its effort.
    assert label("opus-5", "xhigh") == "Opus 5 · Extra High"
    assert label("composer-2.5", "default") == "Composer 2.5"
