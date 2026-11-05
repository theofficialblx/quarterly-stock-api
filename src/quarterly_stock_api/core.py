"""Calendar-quarter alignment for stock-price and macroeconomic CSV data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd


class MergeValidationError(ValueError):
    """An input cannot be aligned safely without changing or guessing its data."""


@dataclass(frozen=True)
class MergeResult:
    """Merged observations and a JSON-compatible description of the merge."""

    data: pd.DataFrame
    summary: dict[str, Any]


_RESERVED_COLUMNS = {"Quarter", "Quarter_End", "Match_Status", "Stock_Date", "Macro_Date"}
_QUARTER_PATTERN = re.compile(r"^\s*(\d{4})\s*[Qq]([1-4])\s*$")
_CUTOFF_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FULL_DATE_PATTERN = re.compile(
    r"^\s*(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4})(?:[ T].*)?\s*$"
)


def _is_full_date(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_FULL_DATE_PATTERN.fullmatch(value))
    return isinstance(value, (date, datetime, pd.Timestamp))


def _validate_table(data: pd.DataFrame, date_column: str, label: str) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise MergeValidationError(f"{label} must be a pandas DataFrame.")
    if data.empty:
        raise MergeValidationError(f"{label} contains no data rows.")
    if not data.columns.is_unique:
        raise MergeValidationError(f"{label} contains duplicate column names.")
    if any(not isinstance(name, str) or not name.strip() for name in data.columns):
        raise MergeValidationError(f"{label} column names must be non-empty strings.")
    if date_column not in data.columns:
        raise MergeValidationError(f"{label} is missing date column {date_column!r}.")
    reserved = sorted(_RESERVED_COLUMNS.intersection(data.columns))
    if reserved:
        raise MergeValidationError(
            f"{label} contains reserved output columns: {', '.join(reserved)}. "
            "Rename those input columns first."
        )
    if data.select_dtypes(include="number").isin([float("inf"), float("-inf")]).any().any():
        raise MergeValidationError(f"{label} contains infinite numeric values.")
    return data.copy(deep=True).reset_index(drop=True)


def _date_values(values: pd.Series, label: str) -> pd.Series:
    # Date-only CSVs are the normal input. For timestamp inputs, use the UTC
    # calendar date consistently; reject numeric values rather than treating
    # them as nanoseconds after 1970-01-01.
    date_like = values.map(_is_full_date)
    dates = (
        pd.to_datetime(values.where(date_like), format="mixed", errors="coerce", utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
    )
    invalid = dates.isna()
    if invalid.any():
        rows = ", ".join(str(int(index) + 2) for index in values.index[invalid][:5])
        raise MergeValidationError(
            f"{label} has missing or invalid dates at CSV row(s) {rows}. "
            "Use complete dates such as 2025-03-31 or 3/31/2025."
        )
    return dates


def _macro_quarters(values: pd.Series) -> pd.PeriodIndex:
    quarters: list[pd.Period] = []
    invalid_rows: list[int] = []
    for index, value in values.items():
        match = _QUARTER_PATTERN.fullmatch(value) if isinstance(value, str) else None
        if match:
            try:
                period = pd.Period(year=int(match[1]), quarter=int(match[2]), freq="Q")
                # Output includes a real quarter-end date. Reject quarters
                # outside pandas' timestamp range as a validation error.
                period.end_time
                quarters.append(period)
                continue
            except (ValueError, OverflowError):
                pass
        elif _is_full_date(value):
            parsed = pd.to_datetime(value, errors="coerce", utc=True)
            if not pd.isna(parsed):
                quarters.append(parsed.tz_localize(None).to_period("Q"))
                continue
        invalid_rows.append(int(index) + 2)
        quarters.append(pd.NaT)
    if invalid_rows:
        rows = ", ".join(str(row) for row in invalid_rows[:5])
        raise MergeValidationError(
            f"Macro data has missing or invalid dates at CSV row(s) {rows}. "
            "Use YYYY Q1 through YYYY Q4, YYYYQ1 through YYYYQ4, or complete dates."
        )
    return pd.PeriodIndex(quarters, freq="Q")


def _quarter_label(period: pd.Period) -> str:
    return f"{period.year} Q{period.quarter}"


def merge_quarterly_data(
    stock: pd.DataFrame,
    macro: pd.DataFrame,
    *,
    stock_date_column: str = "Date",
    macro_date_column: str = "Date",
    join: str = "outer",
    selection: str = "quarter_end_month",
    stock_through: str | None = None,
) -> MergeResult:
    """Align stock observations and one macro scenario by calendar quarter.

    ``quarter_end_month`` reproduces the teacher's selection rule: keep the
    last available stock date in March, June, September, or December. It does
    not invent a closing price for the literal final day of those months.
    ``last_observation`` also permits a quarter whose last record is in another
    month, so a partial quarter can be included.

    ``join`` follows pandas' outer/inner/left/right meanings; stock is the left
    table. ``stock_through`` is an inclusive YYYY-MM-DD cutoff, applied before
    selecting observations. Input frames are never modified. Timestamp dates
    use the UTC calendar date. Remaining values, including missing economic
    observations, are preserved rather than filled or transformed.
    """
    if join not in {"outer", "inner", "left", "right"}:
        raise MergeValidationError("join must be outer, inner, left, or right.")
    if selection not in {"quarter_end_month", "last_observation"}:
        raise MergeValidationError("selection must be quarter_end_month or last_observation.")
    stock_data = _validate_table(stock, stock_date_column, "Stock data")
    macro_data = _validate_table(macro, macro_date_column, "Macro data")
    stock_dates = _date_values(stock_data[stock_date_column], "Stock data")
    if stock_dates.duplicated().any():
        repeated = stock_dates[stock_dates.duplicated(keep=False)].dt.strftime("%Y-%m-%d").unique()
        raise MergeValidationError(
            "Stock data has duplicate calendar dates: "
            + ", ".join(repeated[:5])
            + ". Supply one observation per date."
        )
    macro_quarters = _macro_quarters(macro_data[macro_date_column])
    if macro_quarters.duplicated().any():
        repeated = macro_quarters[macro_quarters.duplicated(keep=False)].unique()
        raise MergeValidationError(
            "Macro data has duplicate quarters: "
            + ", ".join(_quarter_label(period) for period in repeated[:5])
            + ". Supply one macro scenario with one row per quarter."
        )

    cutoff: pd.Timestamp | None = None
    if stock_through is not None:
        if not isinstance(stock_through, str) or not _CUTOFF_PATTERN.fullmatch(stock_through):
            raise MergeValidationError("stock_through must be a YYYY-MM-DD date.")
        try:
            cutoff = pd.Timestamp(date.fromisoformat(stock_through))
        except ValueError as error:
            raise MergeValidationError("stock_through must be a valid YYYY-MM-DD date.") from error
    allowed = stock_dates if cutoff is None else stock_dates[stock_dates <= cutoff]
    dropped_after_cutoff = int(len(stock_dates) - len(allowed))
    candidates = allowed
    if selection == "quarter_end_month":
        candidates = candidates[candidates.dt.month.isin([3, 6, 9, 12])]
    candidates = candidates.sort_values()
    selected_dates = candidates.groupby(candidates.dt.to_period("Q")).tail(1)
    selected_quarters = pd.PeriodIndex(selected_dates.dt.to_period("Q"), freq="Q")

    stock_columns = [name for name in stock_data.columns if name != stock_date_column]
    macro_columns = [name for name in macro_data.columns if name != macro_date_column]
    shared = set(stock_columns).intersection(macro_columns)
    stock_names = {name: f"{name}_stock" if name in shared else name for name in stock_columns}
    macro_names = {name: f"{name}_macro" if name in shared else name for name in macro_columns}
    all_output_names = [*stock_names.values(), *macro_names.values()]
    if len(all_output_names) != len(set(all_output_names)):
        raise MergeValidationError(
            "Input column names would collide after adding _stock/_macro suffixes. "
            "Rename the overlapping input columns."
        )

    left = stock_data.loc[selected_dates.index, stock_columns].rename(columns=stock_names)
    left.insert(0, "Stock_Date", selected_dates.dt.strftime("%Y-%m-%d"))
    left.index = selected_quarters
    right = macro_data[macro_columns].rename(columns=macro_names)
    right.insert(0, "Macro_Date", macro_data[macro_date_column])
    right.index = macro_quarters
    indicator = "__quarter_merge_indicator__"
    while indicator in all_output_names:
        indicator += "_"
    merged = pd.merge(
        left,
        right,
        how=join,
        left_index=True,
        right_index=True,
        validate="one_to_one",
        indicator=indicator,
    ).sort_index()
    status = (
        merged.pop(indicator)
        .astype(object)
        .map({"both": "both", "left_only": "stock_only", "right_only": "macro_only"})
    )
    merged.insert(0, "Match_Status", status)
    merged.insert(0, "Quarter_End", merged.index.to_timestamp(how="end").strftime("%Y-%m-%d"))
    merged.insert(0, "Quarter", [_quarter_label(period) for period in merged.index])
    merged = merged.reset_index(drop=True)

    matched = int((merged["Match_Status"] == "both").sum())
    stock_only = int((merged["Match_Status"] == "stock_only").sum())
    macro_only = int((merged["Match_Status"] == "macro_only").sum())
    warnings: list[str] = []
    skipped = len(allowed.dt.to_period("Q").unique()) - len(selected_quarters)
    if selection == "quarter_end_month" and skipped:
        warnings.append(
            f"Skipped {skipped} stock quarter(s) with no March, June, September, "
            "or December observation under quarter_end_month selection."
        )
    if not len(selected_dates):
        warnings.append("No stock observations remain after the cutoff and selection rule.")
    if selection == "last_observation":
        warnings.append(
            "last_observation can include partial quarters. The latest available "
            "record does not establish that a quarter is complete."
        )
    if cutoff is not None and cutoff != cutoff.to_period("Q").end_time.normalize():
        warnings.append(
            "The cutoff is applied before quarter selection. A cutoff within a "
            "quarter can leave a partial quarter."
        )
    unmatched_stock = len(selected_quarters.difference(macro_quarters))
    unmatched_macro = len(macro_quarters.difference(selected_quarters))
    if unmatched_stock or unmatched_macro:
        warnings.append(
            f"Input coverage differs: {unmatched_stock} selected stock quarter(s) "
            f"have no macro row and {unmatched_macro} macro quarter(s) have no stock "
            "row. Use an inner join for matched modeling rows and set a historical "
            "stock cutoff when needed to avoid using later stock observations."
        )
    if join != "outer":
        warnings.append(
            f"The {join} join may omit unmatched input quarters; Match_Status "
            "and the row counts describe only the returned rows."
        )
    summary: dict[str, Any] = {
        "stock_rows": int(len(stock_data)),
        "macro_rows": int(len(macro_data)),
        "selected_stock_quarters": int(len(selected_dates)),
        "output_rows": int(len(merged)),
        "matched_quarters": matched,
        "stock_only_quarters": stock_only,
        "macro_only_quarters": macro_only,
        "dropped_stock_rows_after_cutoff": dropped_after_cutoff,
        "selection": selection,
        "join": join,
        "stock_through": stock_through,
        "warnings": warnings,
    }
    return MergeResult(data=merged, summary=summary)
