"""Parser tests against saved copies of the real pages.

These are the regression net for the one failure mode that matters: a source changes shape
and the parser keeps returning plausible-looking numbers.
"""

import pytest
from conftest import fixture

from kvasir.collectors import copilot, cursorbench, stupidlevel


def test_cursorbench_parses_every_row():
    rows, meta = cursorbench.parse(fixture("cursorbench.html"))
    assert len(rows) == 56
    assert meta["benchmark_version"] == "3.2"
    assert [row["rank"] for row in rows] == list(range(1, 57))
    assert all(0 < row["score"] <= 100 for row in rows)
    assert all(row["cost_uusd"] > 0 and row["tokens"] > 0 and row["steps"] > 0 for row in rows)


def test_cursorbench_model_name_ending_in_a_digit():
    """"Composer 2.5" + "56.1%" arrive glued together — the split must not eat the version."""
    rows, _ = cursorbench.parse(fixture("cursorbench.html"))
    composer = next(row for row in rows if row["model_key"] == "composer-2.5")
    assert composer["score"] == 56.1
    assert composer["cost_uusd"] == 440_000


def test_cursorbench_keeps_effort_per_row():
    rows, _ = cursorbench.parse(fixture("cursorbench.html"))
    opus = {row["effort"]: row["score"] for row in rows if row["model_key"] == "opus-5"}
    assert opus == {"max": 70.0, "xhigh": 69.3, "high": 66.7, "medium": 64.3, "low": 62.8}


def test_cursorbench_refuses_a_half_read_page():
    with pytest.raises(ValueError):
        cursorbench.parse("<html><body><div>1Opus 5 Max70.0%$8.2361,83878</div></body></html>")


def test_copilot_prices_are_integer_micro_dollars():
    rows, _ = copilot.parse(fixture("copilot-models-and-pricing.html"))
    opus = next(r for r in rows if r["model_key"] == "opus-5")
    assert opus["input_uusd"] == 5_000_000
    assert opus["output_uusd"] == 25_000_000
    assert opus["category"] == "Powerful"
    assert all(isinstance(r["input_uusd"], int) for r in rows if r["input_uusd"] is not None)


def test_copilot_drops_footnote_markers_from_model_names():
    rows, _ = copilot.parse(fixture("copilot-models-and-pricing.html"))
    keys = {row["model_key"] for row in rows}
    assert "gemini-3.6-flash" in keys
    assert not any(key.endswith("flash1") for key in keys)


def test_copilot_keeps_long_context_tiers_apart():
    rows, _ = copilot.parse(fixture("copilot-models-and-pricing.html"))
    sol = [r for r in rows if r["model_key"] == "gpt-5.6-sol"]
    assert {r["tier"] for r in sol} == {"Default", "Long context"}


def test_stupidlevel_reads_scores_and_trends():
    rows, meta = stupidlevel.parse(fixture("stupidlevel-scores.json"))
    assert meta["row_count"] == len(rows) == 22
    sonnet = next(r for r in rows if r["model_key"] == "sonnet-4.6")
    assert sonnet["score"] == 67
    assert sonnet["trend"] in {"up", "down", "stable"}
    assert sonnet["source_id"]  # needed to pull that model's history


def test_stupidlevel_rejects_a_failed_response():
    with pytest.raises(ValueError):
        stupidlevel.parse('{"success": false, "data": []}')
