"""Behavioral tests for quarter alignment, validation, and source preservation."""

import pandas as pd
import pytest

from quarterly_stock_api.core import MergeValidationError, merge_quarterly_data


def frames():
    # Intentionally unsorted; August has no quarter-ending-month observation.
    stock = pd.DataFrame(
        {
            "Date": [
                "2024-12-31",
                "2024-03-15",
                "2024-08-30",
                "2024-01-31",
                "2024-06-28",
                "2024-03-29",
                "2024-03-01",
            ],
            "Close": [140.0, 105.0, 130.0, 99.0, 120.0, 110.0, 101.0],
        }
    )
    macro = pd.DataFrame(
        {
            "Date": ["2025 Q1", "2024 Q3", "2024 Q1", "2024 Q4", "2024 Q2"],
            "GDP": [2.5, 2.3, 2.1, 2.4, 2.2],
        }
    )
    return stock, macro


def test_default_preserves_teacher_selection_and_outer_join():
    stock, macro = frames()
    result = merge_quarterly_data(stock, macro)
    assert result.data["Quarter"].tolist() == [
        "2024 Q1",
        "2024 Q2",
        "2024 Q3",
        "2024 Q4",
        "2025 Q1",
    ]
    both = result.data[result.data["Match_Status"] == "both"]
    assert both["Stock_Date"].tolist() == ["2024-03-29", "2024-06-28", "2024-12-31"]
    assert both["Close"].tolist() == [110.0, 120.0, 140.0]
    assert result.summary["matched_quarters"] == 3
    assert result.summary["macro_only_quarters"] == 2
    assert result.summary["stock_only_quarters"] == 0
    assert result.summary["output_rows"] == 5


def test_last_observation_is_explicit_opt_in():
    stock, macro = frames()
    result = merge_quarterly_data(stock, macro, selection="last_observation", join="inner")
    q3 = result.data.set_index("Quarter").loc["2024 Q3"]
    assert q3["Stock_Date"] == "2024-08-30"
    assert q3["Close"] == 130.0
    assert len(result.data) == 4


def test_cutoff_is_inclusive_and_applied_before_quarter_selection():
    stock, macro = frames()
    result = merge_quarterly_data(stock, macro, stock_through="2024-03-15", join="inner")
    assert result.data["Stock_Date"].tolist() == ["2024-03-15"]
    assert result.data["Close"].tolist() == [105.0]
    assert result.summary["dropped_stock_rows_after_cutoff"] == 4


def test_quarter_end_uses_real_calendar_dates():
    stock = pd.DataFrame(
        {"Date": ["2024-03-28", "2024-06-28", "2024-09-27", "2024-12-30"], "Close": [1, 2, 3, 4]}
    )
    macro = pd.DataFrame({"Date": ["2024Q1", "2024 Q2", "2024-09-30", "2024-10-01"]})
    result = merge_quarterly_data(stock, macro, join="inner")
    assert result.data["Quarter_End"].tolist() == [
        "2024-03-31",
        "2024-06-30",
        "2024-09-30",
        "2024-12-31",
    ]


@pytest.mark.parametrize(
    "join,quarters",
    [
        ("outer", ["2024 Q1", "2024 Q2", "2024 Q3"]),
        ("inner", ["2024 Q2"]),
        ("left", ["2024 Q1", "2024 Q2"]),
        ("right", ["2024 Q2", "2024 Q3"]),
    ],
)
def test_join_choices_preserve_expected_quarters(join, quarters):
    stock = pd.DataFrame({"Date": ["2024-03-29", "2024-06-28"], "Close": [1, 2]})
    macro = pd.DataFrame({"Date": ["2024 Q2", "2024 Q3"], "GDP": [2, 3]})
    result = merge_quarterly_data(stock, macro, join=join)
    assert result.data["Quarter"].tolist() == quarters
    if join == "outer":
        assert result.data["Match_Status"].tolist() == ["stock_only", "both", "macro_only"]


def test_source_frames_are_not_mutated_and_missing_values_survive():
    stock, macro = frames()
    macro.loc[macro["Date"] == "2024 Q1", "GDP"] = float("nan")
    stock_before, macro_before = stock.copy(deep=True), macro.copy(deep=True)
    result = merge_quarterly_data(stock, macro, join="inner")
    assert pd.isna(result.data.set_index("Quarter").loc["2024 Q1", "GDP"])
    pd.testing.assert_frame_equal(stock, stock_before)
    pd.testing.assert_frame_equal(macro, macro_before)


def test_custom_date_columns_and_colliding_value_columns():
    stock = pd.DataFrame({"TradeDate": ["2024-03-29"], "Value": [10]})
    macro = pd.DataFrame({"Period": ["2024 Q1"], "Value": [20]})
    result = merge_quarterly_data(
        stock, macro, stock_date_column="TradeDate", macro_date_column="Period"
    )
    assert result.data["Value_stock"].tolist() == [10]
    assert result.data["Value_macro"].tolist() == [20]
    assert result.data["Stock_Date"].tolist() == ["2024-03-29"]
    assert result.data["Macro_Date"].tolist() == ["2024 Q1"]


@pytest.mark.parametrize("bad_date", ["not-a-date", "2024-02-30", None, ""])
def test_invalid_stock_dates_are_rejected(bad_date):
    stock = pd.DataFrame({"Date": [bad_date], "Close": [1]})
    macro = pd.DataFrame({"Date": ["2024 Q1"]})
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


@pytest.mark.parametrize("bad_date", ["2024 Q5", "not-a-quarter", None, ""])
def test_invalid_macro_dates_are_rejected(bad_date):
    stock = pd.DataFrame({"Date": ["2024-03-29"], "Close": [1]})
    macro = pd.DataFrame({"Date": [bad_date]})
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


def test_duplicate_stock_dates_are_rejected_before_aggregation():
    stock = pd.DataFrame({"Date": ["2024-03-29", "2024-03-29"], "Close": [1, 2]})
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, pd.DataFrame({"Date": ["2024 Q1"]}))


def test_duplicate_macro_quarters_in_different_date_formats_are_rejected():
    stock = pd.DataFrame({"Date": ["2024-03-29"], "Close": [1]})
    macro = pd.DataFrame({"Date": ["2024 Q1", "2024-03-31"]})
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


@pytest.mark.parametrize("side", ["stock", "macro"])
def test_missing_date_header_is_rejected(side):
    stock, macro = frames()
    if side == "stock":
        stock = stock.drop(columns="Date")
    else:
        macro = macro.drop(columns="Date")
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


@pytest.mark.parametrize("side", ["stock", "macro"])
def test_empty_source_is_rejected(side):
    stock, macro = frames()
    if side == "stock":
        stock = stock.iloc[:0]
    else:
        macro = macro.iloc[:0]
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


@pytest.mark.parametrize("side", ["stock", "macro"])
def test_duplicate_column_names_are_rejected(side):
    stock, macro = frames()
    if side == "stock":
        stock.columns = ["Date", "Date"]
    else:
        macro.columns = ["Date", "Date"]
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


@pytest.mark.parametrize(
    "reserved", ["Quarter", "Quarter_End", "Match_Status", "Stock_Date", "Macro_Date"]
)
def test_reserved_output_columns_are_rejected(reserved):
    stock, macro = frames()
    macro[reserved] = 1
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro)


@pytest.mark.parametrize(
    "option", [{"join": "bad"}, {"selection": "bad"}, {"stock_through": "bad"}]
)
def test_invalid_options_are_rejected(option):
    stock, macro = frames()
    with pytest.raises(MergeValidationError):
        merge_quarterly_data(stock, macro, **option)
