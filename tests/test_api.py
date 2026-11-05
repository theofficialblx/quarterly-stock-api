"""Public upload API tests use synthetic data only."""

from io import StringIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quarterly_stock_api.api import app


@pytest.fixture
def client():
    with TestClient(app) as instance:
        yield instance


def uploads(
    stock=b"Date,Close\n2024-03-15,10\n2024-03-28,12\n", macro=b"Date,GDP\n2024 Q1,2\n2024 Q2,\n"
):
    return {
        "stock_file": ("stock.csv", stock, "text/csv"),
        "macro_file": ("macro.csv", macro, "text/csv"),
    }


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_csv_response_is_downloadable_and_has_no_generated_index(client):
    response = client.post("/merge", files=uploads())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    result = pd.read_csv(StringIO(response.text))
    assert result.columns[0] == "Quarter"
    assert not any(column.startswith("Unnamed:") for column in result.columns)
    assert result["Quarter"].tolist() == ["2024 Q1", "2024 Q2"]
    assert result["Close"].iloc[0] == 12


def test_json_response_uses_null_for_missing_values(client):
    response = client.post("/merge", files=uploads(), data={"output_format": "json"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["matched_quarters"] == 1
    assert payload["data"][0]["Close"] == 12
    assert payload["data"][1]["GDP"] is None
    assert payload["data"][1]["Close"] is None
    assert payload["data"][1]["Match_Status"] == "macro_only"
    assert "NaN" not in response.text


def test_form_options_reach_quarter_selection(client):
    stock = b"Date,Close\n2024-03-15,10\n2024-03-28,12\n2024-05-31,20\n"
    response = client.post(
        "/merge",
        files=uploads(stock=stock),
        data={
            "output_format": "json",
            "selection": "last_observation",
            "join": "inner",
            "stock_through": "2024-03-15",
        },
    )
    assert response.status_code == 200
    assert [row["Close"] for row in response.json()["data"]] == [10]


@pytest.mark.parametrize(
    "stock",
    [
        b"",
        b"Price\n12\n",
        b"Date,Close\ninvalid,12\n",
        b'Date,Close\n"unterminated,12\n',
        b"\xff\xfe\x00\x80",
        b"Date,Close\n2024-03-28,12\n2024-03-28,13\n",
    ],
)
def test_malformed_uploads_return_client_errors(client, stock):
    response = client.post("/merge", files=uploads(stock=stock))
    assert response.status_code == 422
    assert "detail" in response.json()


def test_duplicate_macro_quarters_return_client_error(client):
    response = client.post("/merge", files=uploads(macro=b"Date,GDP\n2024 Q1,2\n2024Q1,3\n"))
    assert response.status_code == 422


@pytest.mark.parametrize(
    "options",
    [
        {"join": "unknown"},
        {"selection": "unknown"},
        {"output_format": "xml"},
        {"stock_through": "invalid"},
    ],
)
def test_invalid_form_options_return_client_errors(client, options):
    response = client.post("/merge", files=uploads(), data=options)
    assert response.status_code == 422


def test_missing_upload_returns_client_error(client):
    response = client.post("/merge", files={"stock_file": uploads()["stock_file"]})
    assert response.status_code == 422


def test_upload_limit_is_enforced(client):
    response = client.post("/merge", files=uploads(stock=b"x" * (10 * 1024 * 1024 + 1)))
    assert response.status_code == 413
