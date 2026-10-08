"""Parser tests against saved copies of the real pages.

These are the regression net for the one failure mode that matters: a source changes shape
and the parser keeps returning plausible-looking numbers.
"""

import pytest
from conftest import fixture

from kvasir.collectors import artificialanalysis, copilot, stupidlevel

AA_BOARD = "artificialanalysis-leaderboard.html"
AA_VARIANT = "artificialanalysis-variant-page.html"
# A model page from September 2026, when every page carried every variant. Its records have the
# shape a variant page still has, so it tests _row() on 665 of them.
AA_RECORDS = "artificialanalysis-model-page.html"


def aa_variant(slug: str) -> dict:
    return artificialanalysis.parse_variant(fixture(AA_RECORDS), slug)[0]


def aa_known(board: list[dict]) -> dict[str, dict]:
    """An archive that knows every variant, as a run after the first one has it."""
    return {
        entry["slug"]: {
            "model_key": entry["slug"],
            "effort": "default",
            "vendor": "",
            "released": "",
            "source_slug": entry["slug"],
            "output_tokens": None,
            "task_seconds": 60.0,
            **artificialanalysis._measured(entry),
        }
        for entry in board
    }


def test_artificialanalysis_reads_the_whole_leaderboard():
    """The leaderboard carries every variant — not just the top twenty of a chart."""
    board = artificialanalysis.parse_board(fixture(AA_BOARD))
    assert len(board) == 697
    priced = [entry for entry in board if entry.get("intelligenceIndexCostPerTask") is not None]
    assert len(priced) == 185
    # A priced score is a measured one; estimates are for variants nobody ran the index on.
    assert not any(entry.get("intelligenceIndexIsEstimated") for entry in priced)


def test_artificialanalysis_reads_a_variant_page():
    row, version = artificialanalysis.parse_variant(fixture(AA_VARIANT), "claude-haiku-5-5-low")
    assert version == "4.3"
    assert (row["model_key"], row["effort"]) == ("haiku-5.5", "low")
    assert row["cost_uusd"] == 24_459
    assert row["task_seconds"] == 62.4
    assert row["released"] == "2026-10-07"


def test_artificialanalysis_reads_a_slug_with_dots_and_capitals():
    """Eight slugs on the board are not lowercase kebab; each must still find its record."""
    raw = fixture(AA_VARIANT).replace("claude-haiku-5-5-low", "QwQ-0.6b-Preview")
    row, _ = artificialanalysis.parse_variant(raw, "QwQ-0.6b-Preview")
    assert row["source_slug"] == "QwQ-0.6b-Preview"


def test_artificialanalysis_leaderboard_numbers_match_the_variant_page():
    """Numbers come from the leaderboard, identity and clock from the page: same runs, same digits."""
    board = artificialanalysis.parse_board(fixture(AA_BOARD))
    entry = next(entry for entry in board if entry["slug"] == "claude-haiku-5-5-low")
    row, _ = artificialanalysis.parse_variant(fixture(AA_VARIANT), "claude-haiku-5-5-low")
    measured = artificialanalysis._measured(entry)
    assert measured == {key: row[key] for key in measured}


def test_artificialanalysis_reads_a_page_only_when_the_archive_cannot_answer():
    board = artificialanalysis.parse_board(fixture(AA_BOARD))
    entry = next(entry for entry in board if entry["slug"] == "claude-haiku-5-5-low")
    row, _ = artificialanalysis.parse_variant(fixture(AA_VARIANT), "claude-haiku-5-5-low")
    assert artificialanalysis.needs_page(entry, None)  # never seen
    assert not artificialanalysis.needs_page(entry, row)  # nothing moved
    assert artificialanalysis.needs_page(entry, dict(row, cost_uusd=1))  # re-run: a new clock
    assert artificialanalysis.needs_page(entry, dict(row, task_seconds=None))  # priced, untimed
    assert not artificialanalysis.needs_page(entry, None, folded=True)
    unpriced = next(e for e in board if e.get("intelligenceIndexCostPerTask") is None)
    assert not artificialanalysis.needs_page(unpriced, {"score": -1, "cost_uusd": None})


def test_artificialanalysis_merge_takes_numbers_from_the_board_and_time_from_the_page():
    board = artificialanalysis.parse_board(fixture(AA_BOARD))
    known = aa_known(board)
    row, _ = artificialanalysis.parse_variant(fixture(AA_VARIANT), "claude-haiku-5-5-low")
    known.pop("claude-haiku-5-5-low")
    rows, meta = artificialanalysis.merge(
        board, known, {}, {"claude-haiku-5-5-low": row}, "4.3"
    )
    haiku = next(r for r in rows if r["source_slug"] == "claude-haiku-5-5-low")
    assert haiku == row
    assert meta["benchmark_version"] == "4.3"
    assert meta["row_count"] == len(rows) == 697


def test_artificialanalysis_merge_folds_variants_and_remembers_the_losers():
    board = artificialanalysis.parse_board(fixture(AA_BOARD))
    known = aa_known(board)
    known["claude-haiku-5-5-low"]["model_key"] = known["claude-haiku-5-5"]["model_key"]
    rows, meta = artificialanalysis.merge(board, known, {}, {}, "4.3")
    assert len({(r["model_key"], r["effort"]) for r in rows}) == len(rows) == 696
    assert set(meta["folded"]) == {"claude-haiku-5-5-low"}
    # The next run knows the loser without its page, and folds it again.
    known.pop("claude-haiku-5-5-low")
    again, _ = artificialanalysis.merge(board, known, meta["folded"], {}, "4.3")
    assert len(again) == 696


def test_artificialanalysis_merge_refuses_a_variant_it_cannot_identify():
    board = artificialanalysis.parse_board(fixture(AA_BOARD))
    known = aa_known(board)
    known.pop("claude-haiku-5-5-low")
    with pytest.raises(ValueError):
        artificialanalysis.merge(board, known, {}, {}, "4.3")


def test_artificialanalysis_keeps_effort_per_row():
    opus = {e: aa_variant(f"claude-opus-5-5-{e}") for e in ("low", "medium", "high", "xhigh")}
    opus["max"] = aa_variant("claude-opus-5-5")
    assert {effort: row["effort"] for effort, row in opus.items()} == {e: e for e in opus}
    assert {row["model_key"] for row in opus.values()} == {"opus-5.5"}
    assert opus["max"]["score"] == 57.6
    assert opus["max"]["cost_uusd"] == 5_982_012
    assert opus["high"]["first_answer_seconds"] == 12.7
    assert opus["high"]["tokens_per_second"] == 84.6
    assert opus["max"]["tokens_per_second"] is None  # not timed yet: absent, never zero
    # Time per task is published in seconds; their chart shows minutes (Opus 5.5 High: 4.4).
    assert opus["high"]["task_seconds"] == 266.4
    assert opus["max"]["task_seconds"] is None


def test_artificialanalysis_money_is_integer_micro_dollars():
    board = artificialanalysis.parse_board(fixture(AA_BOARD))
    rows, _ = artificialanalysis.merge(board, aa_known(board), {}, {}, "4.3")
    priced = [row for row in rows if row["cost_uusd"] is not None]
    assert priced and all(isinstance(row["cost_uusd"], int) for row in priced)


def test_artificialanalysis_keeps_an_unpriced_release_unpriced():
    """GPT-6 was timed and scored on release day, but not priced — never invent the price."""
    luna = [aa_variant(slug) for slug in ("gpt-6-luna-xhigh", "gpt-6-luna-medium")]
    assert all(row["cost_uusd"] is None for row in luna)
    assert all(row["score"] is not None for row in luna)


def test_artificialanalysis_gives_non_reasoning_modes_no_effort():
    assert aa_variant("claude-sonnet-5-non-reasoning")["effort"] == "default"


def test_artificialanalysis_refuses_a_half_read_page():
    """A payload that lost most of its records must fail, not return a plausible subset."""
    raw = fixture(AA_BOARD)
    cut = raw[: len(raw) // 5] + '"])</script></body></html>'
    with pytest.raises(ValueError):
        artificialanalysis.parse_board(cut)
    with pytest.raises(ValueError):
        artificialanalysis.parse_board("<html><body>Intelligence Index v4.3</body></html>")
    with pytest.raises(ValueError):
        artificialanalysis.parse_variant(fixture(AA_VARIANT), "claude-opus-5-5")


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
