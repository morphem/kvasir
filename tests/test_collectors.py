"""Parser tests against saved copies of the real pages.

These are the regression net for the one failure mode that matters: a source changes shape
and the parser keeps returning plausible-looking numbers.
"""

import pytest
from conftest import fixture

from kvasir.collectors import artificialanalysis, copilot, stupidlevel

AA_PAGE = "artificialanalysis-model-page.html"


def test_artificialanalysis_reads_the_whole_board():
    """Every model page carries every variant — not just the top twenty of a chart."""
    rows, meta = artificialanalysis.parse(fixture(AA_PAGE))
    assert meta["benchmark_version"] == "4.3"
    assert meta["row_count"] == len(rows) == 593
    assert meta["priced_count"] == 142
    assert len({(row["model_key"], row["effort"]) for row in rows}) == len(rows)


def test_artificialanalysis_keeps_effort_per_row():
    rows, _ = artificialanalysis.parse(fixture(AA_PAGE))
    opus = {row["effort"]: row for row in rows if row["model_key"] == "opus-5.5"}
    assert set(opus) == {"low", "medium", "high", "xhigh", "max"}
    assert opus["max"]["score"] == 57.6
    assert opus["max"]["cost_uusd"] == 5_982_012
    assert opus["high"]["first_answer_seconds"] == 12.7
    assert opus["high"]["tokens_per_second"] == 84.6
    assert opus["max"]["tokens_per_second"] is None  # not timed yet: absent, never zero
    # Time per task is published in seconds; their chart shows minutes (Opus 5.5 High: 4.4).
    assert opus["high"]["task_seconds"] == 266.4
    assert opus["max"]["task_seconds"] is None


def test_artificialanalysis_money_is_integer_micro_dollars():
    rows, _ = artificialanalysis.parse(fixture(AA_PAGE))
    priced = [row for row in rows if row["cost_uusd"] is not None]
    assert priced and all(isinstance(row["cost_uusd"], int) for row in priced)


def test_artificialanalysis_keeps_an_unpriced_release_unpriced():
    """GPT-6 was timed and scored on release day, but not priced — never invent the price."""
    rows, _ = artificialanalysis.parse(fixture(AA_PAGE))
    luna = [row for row in rows if row["model_key"] == "gpt-6-luna"]
    assert luna and all(row["cost_uusd"] is None for row in luna)
    assert all(row["score"] is not None for row in luna)


def test_artificialanalysis_gives_non_reasoning_modes_no_effort():
    rows, _ = artificialanalysis.parse(fixture(AA_PAGE))
    sonnet = next(row for row in rows if row["source_slug"] == "claude-sonnet-5-non-reasoning")
    assert sonnet["effort"] == "default"


def test_artificialanalysis_refuses_a_half_read_page():
    """A payload that lost most of its records must fail, not return a plausible subset."""
    raw = fixture(AA_PAGE)
    cut = raw[: len(raw) // 5] + "</body></html>"
    with pytest.raises(ValueError):
        artificialanalysis.parse(cut)
    with pytest.raises(ValueError):
        artificialanalysis.parse("<html><body>Intelligence Index v4.3</body></html>")


def test_copilot_prices_are_integer_micro_dollars():
    rows, _ = copilot.parse(fixture("copilot-models-and-pricing.html"))
    opus = next(r for r in rows if r["model_key"] == "opus-5.5")
    assert opus["input_uusd"] == 4_000_000
    assert opus["output_uusd"] == 20_000_000
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


def test_stupidlevel_says_what_a_401_means():
    """The source went key-only in September; the run log must say that in words."""
    import asyncio

    class Response:
        status_code = 401
        text = '{"error": "api_key_required"}'

    class Client:
        def __init__(self):
            self.headers_seen = None

        async def get(self, url, headers=None):
            self.headers_seen = headers
            return Response()

    with pytest.raises(PermissionError) as failure:
        asyncio.run(stupidlevel.fetch(Client()))
    assert "API key" in str(failure.value)
    assert "KVASIR_STUPIDLEVEL_API_KEY" in str(failure.value)


def test_stupidlevel_uses_the_v1_endpoint_when_a_key_is_set(monkeypatch):
    import asyncio

    from kvasir.config import Settings

    # Settings is frozen, and the collector reads the module singleton at call time.
    monkeypatch.setattr("kvasir.config.settings", Settings(stupidlevel_api_key="asl_live_test"))

    class Response:
        status_code = 200
        text = None

        def raise_for_status(self):
            pass

    calls = {}

    class Client:
        async def get(self, url, headers=None):
            calls["url"] = url
            calls["headers"] = headers or {}
            response = Response()
            response.text = open(
                "tests/fixtures/stupidlevel-scores.json", encoding="utf-8"
            ).read()
            return response

    rows, _ = asyncio.run(stupidlevel.fetch(Client()))
    assert calls["url"] == stupidlevel.URL_V1
    assert calls["headers"]["Authorization"] == "Bearer asl_live_test"
    assert rows
