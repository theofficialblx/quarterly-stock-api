"""Strict, shared CSV loading for uploads and local files."""

import csv
import io
from pathlib import Path

import pandas as pd

from .core import MergeValidationError


def read_csv_bytes(content: bytes, *, label: str = "CSV") -> pd.DataFrame:
    """Read UTF-8 CSV, rejecting ambiguous headers and inconsistent row widths."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MergeValidationError(f"{label} must be a UTF-8 CSV file.") from exc
    if not text.strip():
        raise MergeValidationError(f"{label} is empty.")
    try:
        rows = csv.reader(io.StringIO(text), strict=True)
        header = next(rows)
        names = [name.strip() for name in header]
        if not names or any(not name for name in names):
            raise MergeValidationError(f"{label} must have a nonempty name for every column.")
        if len(set(names)) != len(names):
            raise MergeValidationError(f"{label} contains duplicate column names.")
        for row in rows:
            if not row:  # pandas also ignores empty lines
                continue
            if len(row) != len(names):
                raise MergeValidationError(
                    f"{label} has {len(row)} fields near line {rows.line_num}; "
                    f"the header has {len(names)}."
                )
        data = pd.read_csv(io.StringIO(text))
        data.columns = names
        return data
    except (csv.Error, pd.errors.ParserError, pd.errors.EmptyDataError, StopIteration) as exc:
        raise MergeValidationError(f"{label} is not a valid rectangular CSV file.") from exc


def read_csv_path(path: str | Path, *, label: str = "CSV") -> pd.DataFrame:
    return read_csv_bytes(Path(path).read_bytes(), label=label)
