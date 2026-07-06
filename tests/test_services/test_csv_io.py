"""Unit tests for the shared CSV export/import helpers -- no Qt, no network.
Covers the escaping cases CSV commonly gets wrong: commas, quotes, embedded
newlines, Unicode, and empty values."""

from __future__ import annotations

from gcm.services.csv_io import export_rows, read_rows


def test_export_then_read_round_trips_plain_values(tmp_path):
    path = tmp_path / "out.csv"
    export_rows(path, ["Name", "Status"], [["Jane Doe", "Enabled"], ["John Roe", "Disabled"]])

    rows = read_rows(path)

    assert rows == [
        {"Name": "Jane Doe", "Status": "Enabled"},
        {"Name": "John Roe", "Status": "Disabled"},
    ]


def test_export_then_read_round_trips_commas_quotes_and_newlines(tmp_path):
    path = tmp_path / "out.csv"
    tricky = 'Smith, Jane "JJ"\nSecond line'
    export_rows(path, ["Name"], [[tricky]])

    rows = read_rows(path)

    assert rows == [{"Name": tricky}]


def test_export_then_read_round_trips_unicode(tmp_path):
    path = tmp_path / "out.csv"
    name = "José Núñez 日本語 🎉"
    export_rows(path, ["Name"], [[name]])

    rows = read_rows(path)

    assert rows == [{"Name": name}]


def test_export_converts_none_cells_to_empty_string(tmp_path):
    path = tmp_path / "out.csv"
    export_rows(path, ["Name", "Mail"], [["Jane", None]])

    rows = read_rows(path)

    assert rows == [{"Name": "Jane", "Mail": ""}]


def test_read_rows_treats_missing_cells_as_empty_string(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("Name,Mail\nJane,\n", encoding="utf-8")

    rows = read_rows(path)

    assert rows == [{"Name": "Jane", "Mail": ""}]


def test_export_rows_returns_row_count(tmp_path):
    path = tmp_path / "out.csv"
    count = export_rows(path, ["Name"], [["A"], ["B"], ["C"]])
    assert count == 3


def test_export_rows_handles_zero_rows(tmp_path):
    path = tmp_path / "out.csv"
    count = export_rows(path, ["Name"], [])
    assert count == 0
    assert read_rows(path) == []
