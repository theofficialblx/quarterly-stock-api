"""Test the file boundary and protect source files from accidental overwrite."""

import json

import pytest
from fastapi.testclient import TestClient

from quarterly_stock_api.api import app
from quarterly_stock_api.cli import main
from quarterly_stock_api.core import MergeValidationError, merge_quarterly_data
from quarterly_stock_api.csv_io import read_csv_bytes


@pytest.mark.parametrize(
    "content",
    [
        b"Date,Date\n2024-03-29,2024-03-29\n",
        b"Date,Close\n2024-03-29,10,extra\n",
        b"Date,Close\n2024-03-29\n",
        b"Date,\n2024-03-29,10\n",
        b"\xff\xfe",
    ],
)
def test_invalid_csv_boundaries(content):
    with pytest.raises(MergeValidationError):
        read_csv_bytes(content)


@pytest.mark.parametrize("invalid", ["03/2025", "2025-03", "2025", "March 2025"])
@pytest.mark.parametrize("table", ["stock", "macro"])
def test_incomplete_dates_never_become_quarter_observations(invalid, table):
    stock = read_csv_bytes(b"Date,Close\n2025-03-28,10\n")
    macro = read_csv_bytes(b"Date,GDP\n2025 Q1,2\n")
    (stock if table == "stock" else macro).loc[0, "Date"] = invalid
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


def test_json_preserves_float_precision():
    expected = 1.123456789012345
    with TestClient(app) as client:
        response = client.post(
            "/merge",
            files={
                "stock_file": ("stock.csv", f"Date,Close\n2025-03-28,{expected}\n"),
                "macro_file": ("macro.csv", "Date,GDP\n2025 Q1,2\n"),
            },
            data={"output_format": "json"},
        )
    assert response.status_code == 200
    assert response.json()["data"][0]["Close"] == expected


def test_infinite_numeric_input_is_rejected():
    stock = read_csv_bytes(b"Date,Close\n2025-03-28,inf\n")
    macro = read_csv_bytes(b"Date,GDP\n2025 Q1,2\n")
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


def test_cli_outputs_report_and_never_overwrites_sources(tmp_path):
    stock = tmp_path / "stock.csv"
    macro = tmp_path / "macro.csv"
    out = tmp_path / "output.csv"
    report = tmp_path / "summary.json"
    stock.write_text("Date,Close\n2025-03-28,10\n")
    macro.write_text("Date,GDP\n2025 Q1,2\n")
    args = ["--stock", str(stock), "--macro", str(macro)]
    assert main(args + ["--output", str(out), "--report", str(report)]) == 0
    assert json.loads(report.read_text())["matched_quarters"] == 1
    assert out.read_text().startswith("Quarter,Quarter_End,Match_Status,")
    assert main(args + ["--output", str(out)]) == 2
    before = stock.read_bytes()
    assert main(args + ["--output", str(stock), "--force"]) == 2
    assert stock.read_bytes() == before


def test_utf8_bom_and_header_whitespace():
    data = read_csv_bytes(b"\xef\xbb\xbf Date , Close \n2025-03-28,10\n")
    assert data.columns.tolist() == ["Date", "Close"]


def test_cli_same_output_and_report_is_rejected(tmp_path):
    out = tmp_path / "same.csv"
    assert (
        main(
            [
                "--stock",
                "missing.csv",
                "--macro",
                "missing2.csv",
                "--output",
                str(out),
                "--report",
                str(out),
            ]
        )
        == 2
    )
    assert not out.exists()
