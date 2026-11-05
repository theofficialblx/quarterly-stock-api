"""Command-line entry points using the same engine as the HTTP API."""

import argparse
import json
import sys
from pathlib import Path

from .core import MergeValidationError, merge_quarterly_data
from .csv_io import read_csv_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge stock and macro CSVs by calendar quarter.")
    parser.add_argument("--stock", required=True, type=Path, help="Stock-price CSV")
    parser.add_argument("--macro", required=True, type=Path, help="One macroeconomic CSV")
    parser.add_argument("--output", type=Path, default=Path("Merged_Data.csv"))
    parser.add_argument("--report", type=Path, help="Optional JSON summary file")
    parser.add_argument("--join", choices=["outer", "inner", "left", "right"], default="outer")
    parser.add_argument(
        "--selection",
        choices=["quarter_end_month", "last_observation"],
        default="quarter_end_month",
    )
    parser.add_argument("--stock-through", help="Inclusive stock cutoff, YYYY-MM-DD")
    parser.add_argument("--stock-date-column", default="Date")
    parser.add_argument("--macro-date-column", default="Date")
    parser.add_argument("--force", action="store_true", help="Replace existing output/report files")
    args = parser.parse_args(argv)
    try:
        inputs = {args.stock.resolve(), args.macro.resolve()}
        targets = [p for p in (args.output, args.report) if p is not None]
        if len({p.resolve() for p in targets}) != len(targets):
            raise MergeValidationError("Output and report must use different file paths.")
        for target in targets:
            if target.resolve() in inputs:
                raise MergeValidationError("Output files must not overwrite either source CSV.")
            if target.exists() and not args.force:
                raise MergeValidationError(f"{target} exists; use --force to replace it.")
        result = merge_quarterly_data(
            read_csv_path(args.stock, label="Stock file"),
            read_csv_path(args.macro, label="Macro file"),
            stock_date_column=args.stock_date_column,
            macro_date_column=args.macro_date_column,
            join=args.join,
            selection=args.selection,
            stock_through=args.stock_through,
        )
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
        result.data.to_csv(args.output, index=False)
        summary = json.dumps(result.summary, indent=2, allow_nan=False) + "\n"
        if args.report:
            args.report.write_text(summary, encoding="utf-8")
        print(summary, file=sys.stderr, end="")
        print(f"Saved {len(result.data)} quarters to {args.output}", file=sys.stderr)
        return 0
    except (MergeValidationError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def serve() -> None:
    parser = argparse.ArgumentParser(description="Start the Quarterly Stock API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run("quarterly_stock_api.api:app", host=args.host, port=args.port)
