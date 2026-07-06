"""Shared CSV read/write helpers, used by every exportable page and by bulk
user import. No Qt imports, so it's unit-testable without a display.

Both functions are synchronous -- callers should invoke them via
`loop.run_in_executor(None, ...)` so a large file never blocks the UI
thread, matching the pattern already used for MSAL's blocking sign-in call
in main_window.py.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path


def export_rows(path: str | Path, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> int:
    """Writes a header row plus data rows to a CSV file. Returns the number
    of data rows written.

    `quoting=csv.QUOTE_MINIMAL` (the stdlib default) quotes a field only
    when it contains a comma, quote, or newline, and doubles any embedded
    quote characters -- exactly the escaping CSV readers expect, so cells
    with commas/quotes/newlines round-trip correctly. `newline=""` is
    required by the csv module itself to avoid extra blank lines on
    Windows. `utf-8-sig` adds a BOM so Excel opens Unicode names correctly
    instead of mis-decoding them as the system codepage.
    """
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        row_count = 0
        for row in rows:
            writer.writerow("" if cell is None else cell for cell in row)
            row_count += 1
    return row_count


def read_rows(path: str | Path) -> list[dict[str, str]]:
    """Reads a CSV file into a list of dicts keyed by its header row.

    Missing/empty cells always come back as "" (never None), so callers
    (e.g. bulk import validation) can treat every value as a plain string.
    """
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # DictReader puts any column beyond the header count under a None
        # key (a list of leftover values) -- skip it rather than choke on it.
        return [
            {key: (value or "") for key, value in row.items() if key is not None}
            for row in reader
        ]
