"""Test setup: an isolated data dir, and no network from the app itself.

KVASIR_AUTOSTART=0 keeps the lifespan from collecting on boot, so the API tests run
against data the test put there rather than against whatever the internet says today.
"""

import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ.setdefault("KVASIR_DATA_DIR", tempfile.mkdtemp(prefix="kvasir-test-"))
os.environ.setdefault("KVASIR_AUTOSTART", "0")

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def september_board() -> tuple[list[dict], dict]:
    """The Artificial Analysis board as it stood in September 2026, from a saved model page.

    The planner tests pin numbers on this board. Its records have the shape a variant page
    still has, so it is read with the collector's own _row() and fold().
    """
    from kvasir.collectors import artificialanalysis

    records = artificialanalysis._records(
        artificialanalysis._payload(fixture("artificialanalysis-model-page.html"))
    )
    rows, _ = artificialanalysis.fold([artificialanalysis._row(r) for r in records.values()])
    return rows, {"benchmark_version": "4.3", "row_count": len(rows)}
