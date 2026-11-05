"""Local HTTP API. Interactive file-upload documentation lives at /docs."""

from typing import Annotated, Literal

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .core import MergeValidationError, merge_quarterly_data
from .csv_io import read_csv_bytes

MAX_FILE_BYTES = 10 * 1024 * 1024

app = FastAPI(
    title="Quarterly Stock API",
    version="1.0.0",
    description=(
        "Upload stock prices and one macroeconomic CSV to align them by calendar quarter. "
        "The default follows the classroom helper: use the last observed stock date "
        "in March, June, September, or December, then perform an outer join. "
        "Use an inner join and a historical cutoff when preparing model training data."
    ),
    license_info={"name": "MIT"},
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _read_upload(upload: UploadFile, label: str):
    content = upload.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, f"{label} exceeds the 10 MiB per-file limit.")
    return read_csv_bytes(content, label=label)


@app.post(
    "/merge",
    response_model=None,
    responses={
        200: {
            "description": "Merged CSV download, or JSON with data and summary.",
            "content": {"text/csv": {}, "application/json": {}},
        },
        413: {"description": "A file exceeds 10 MiB."},
        422: {"description": "Invalid CSV, date, column, or merge option."},
    },
)
def merge(
    stock_file: Annotated[UploadFile, File(description="Stock CSV with Date and price columns")],
    macro_file: Annotated[UploadFile, File(description="One macro CSV with a Date column")],
    join: Annotated[Literal["outer", "inner", "left", "right"], Form()] = "outer",
    selection: Annotated[
        Literal["quarter_end_month", "last_observation"], Form()
    ] = "quarter_end_month",
    stock_through: Annotated[
        str | None, Form(description="Optional inclusive stock cutoff, YYYY-MM-DD")
    ] = None,
    output_format: Annotated[Literal["csv", "json"], Form()] = "csv",
    stock_date_column: Annotated[str, Form()] = "Date",
    macro_date_column: Annotated[str, Form()] = "Date",
) -> Response:
    try:
        result = merge_quarterly_data(
            _read_upload(stock_file, "Stock file"),
            _read_upload(macro_file, "Macro file"),
            stock_date_column=stock_date_column,
            macro_date_column=macro_date_column,
            join=join,
            selection=selection,
            stock_through=stock_through or None,
        )
    except MergeValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if output_format == "json":
        # Preserve Python float precision and convert missing cells to JSON null.
        records = result.data.astype(object).where(pd.notna(result.data), None).to_dict("records")
        return JSONResponse({"summary": result.summary, "data": records})
    return Response(
        result.data.to_csv(index=False),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="Merged_Data.csv"',
            "X-Matched-Quarters": str(result.summary["matched_quarters"]),
            "X-Stock-Only-Quarters": str(result.summary["stock_only_quarters"]),
            "X-Macro-Only-Quarters": str(result.summary["macro_only_quarters"]),
        },
    )
