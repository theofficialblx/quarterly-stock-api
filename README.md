# Quarterly Stock API

Merge stock-price observations with quarterly macroeconomic data. Use the same
transformation through a Python function, a command-line tool, or a local HTTP API
with an interactive upload page.

This is a reusable implementation of a classroom data-preparation helper. It
does **not** fit a regression model, backtest, or generate stock-price forecasts.

## Quick start

Install [Python 3.10 or newer](https://www.python.org/downloads/) and Git. Clone
this repository, then open a terminal in its folder:

```bash
git clone https://github.com/theofficialblx/quarterly-stock-api.git
cd quarterly-stock-api
python -m venv .venv
```

On macOS/Linux, use `python3` instead of `python` if that is your Python command.

Activate the environment on macOS/Linux:

```bash
source .venv/bin/activate
```

On Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Then install and start:

```bash
python -m pip install .
quarterly-api
```

Open **http://127.0.0.1:8000/docs**. Expand **POST /merge**, select **Try it out**,
choose your stock and macro CSV files, and select **Execute**. The default response
is a downloadable `Merged_Data.csv`. Choose `output_format=json` to see the data
along with a summary of matched and unmatched quarters. Press Ctrl+C in the
terminal to stop the server. No account or API key is required.

The API runs on your computer. This repository is source code, not a shared
hosted service. Each classmate runs their own copy. Uploaded contents are processed
for that request; this app does not add them to Git or intentionally retain them.
The web framework can temporarily spool large uploads to disk during a request.

## Try the included example

The example files contain **synthetic data**, not a student's assignment.

```bash
quarterly-merge --stock examples/stock.csv --macro examples/macro.csv --output outputs/example.csv --report outputs/example-summary.json
```

Expected result: four matched quarters for 2024, with closes **102, 110, 115,
120**. `Quarter_End` contains the real calendar quarter end; `Stock_Date` retains
the date of the stock observation actually selected.

To use your own files without starting the API:

```bash
quarterly-merge --stock data/stock.csv --macro data/Historic_Domestic.csv --join inner --stock-through 2025-12-31 --output outputs/training.csv --report outputs/training-summary.json
```

Put private inputs in `data/` and generated results in `outputs/`. Both folders are
ignored by Git, as are CSVs outside the synthetic example folder. Existing output
files are preserved unless you supply `--force`. Source CSVs cannot be used as
output paths, even with `--force`.

## What changed from the classroom helper?

- No personal file paths: provide files through uploads, command-line arguments,
  or pandas DataFrames.
- Joins use calendar quarters instead of invented dates on the 30th of a month.
- Rows are sorted before selecting the final observation, and duplicate or invalid
  dates are rejected rather than producing an ambiguous merge.
- An optional stock cutoff is applied before quarterly selection.
- Matched and unmatched quarters are explicitly labeled. Missing values remain
  missing, and CSV exports do not contain an extra index column.

The default selection preserves the teacher's rule: take the final observed stock
date in **March, June, September, or December**. A quarter with no observation in
its ending month is excluded from the selected stock data. For weekly prices,
the selected date can be before the last calendar day of the quarter.

## Input format

Stock CSV:

```csv
Date,Close
2024-03-22,100
2024-03-28,102
2024-06-28,110
```

Macro CSV:

```csv
Scenario Name,Date,Real GDP growth,Unemployment rate
Actual,2024 Q1,2.1,4.0
Actual,2024 Q2,2.4,4.1
```

- CSVs must be UTF-8 (a UTF-8 BOM is supported) with one header row.
- Stock dates can use ISO dates or ordinary U.S. month/day/year dates. Prefer ISO
  dates to avoid ambiguous international date formats.
- Timestamp inputs are normalized to UTC calendar dates; date-only CSVs avoid
  timezone shifts around midnight or quarter boundaries.
- Macro dates accept `2024 Q1`, `2024Q1`, or calendar dates assigned to their quarter.
- Columns default to `Date`; change `stock_date_column` / `macro_date_column` in
  the API or `--stock-date-column` / `--macro-date-column` in the CLI if needed.
- Preserve numeric values and units from the source. Annualized growth rates,
  interest-rate levels, and index levels are not automatically converted.
- One stock observation per date and one macro row per quarter are required.
  Process baseline, severe, and historical files separately. Concatenating
  different scenarios with repeated quarters will be rejected.
- Missing economic values are retained. This tool does not interpolate or fill them.
- Other columns use pandas CSV type inference. Blank cells and conventional pandas
  missing-value markers are treated as missing; identifiers requiring exact text
  types should be loaded explicitly through the Python interface.
- Generated output names `Quarter`, `Quarter_End`, `Match_Status`, `Stock_Date`,
  and `Macro_Date` are reserved. Other overlapping names receive `_stock` and
  `_macro` suffixes.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `join` | `outer` | Keep all quarters from either file. `inner` keeps only matched quarters; `left` keeps selected stock quarters; `right` keeps macro quarters. |
| `selection` | `quarter_end_month` | Teacher's ending-month rule. `last_observation` instead selects the latest available stock date anywhere in a quarter. |
| `stock_through` | unset | Inclusive stock-date cutoff in `YYYY-MM-DD` format. |
| `output_format` | `csv` | HTTP response: downloadable CSV or JSON with `data` and `summary`. |

An outer join is useful for inspecting coverage. It is **not automatically a
model-training dataset**. Check `Match_Status` (`both`, `stock_only`, `macro_only`),
the selected dates, and missing values. An inner join removes unmatched quarters
but does not remove missing economic values within a matched row.

For a forecast starting in 2026 Q1, use historical macro data through 2025 Q4 and
a stock cutoff no later than `2025-12-31` for training. Keep later observed prices
separate for evaluation. This cutoff example is a workflow choice, not a built-in
assumption. `last_observation` can select incomplete quarters; even the default
cannot establish that the last available observation represents a complete
quarter. Inspect coverage before using either selection for modeling.

## HTTP examples

With the API running, request a CSV from a second terminal:

```bash
curl -X POST http://127.0.0.1:8000/merge -F "stock_file=@examples/stock.csv" -F "macro_file=@examples/macro.csv" -F "join=inner" -o Merged_Data.csv
```

For JSON, add `-F "output_format=json"`. For a historical cutoff, add
`-F "stock_through=2025-12-31"`.

`GET /health` returns `{"status":"ok"}`. API validation errors return status 422
with a readable `detail`. Files over **10 MiB each** return status 413. CSV
responses also include `X-Matched-Quarters`, `X-Stock-Only-Quarters`, and
`X-Macro-Only-Quarters` headers.

## Python example

```python
import pandas as pd
from quarterly_stock_api import merge_quarterly_data

result = merge_quarterly_data(
    pd.read_csv("data/stock.csv"),
    pd.read_csv("data/Historic_Domestic.csv"),
    join="inner",
    stock_through="2025-12-31",
)
result.data.to_csv("training.csv", index=False)
print(result.summary)
```

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest
python -m build
```

GitHub Actions runs lint, tests, and package building across Python 3.10–3.13.
Tests use only synthetic data. Contributions should include tests for changes to
selection, validation, or merge behavior.

Optional Docker run:

```bash
docker build -t quarterly-stock-api .
docker run --rm -p 127.0.0.1:8000:8000 quarterly-stock-api
```

The default local service has no authentication. If deploying a shared internet
service, add authentication, HTTPS, request-body limits at the proxy, and rate
limits appropriate to your hosting environment.

## License and attribution

MIT licensed: classmates can clone, use, modify, and share this code. The project
was inspired by the teacher's classroom helper for selecting quarterly stock
observations and merging macroeconomic data. The implementation is newly
structured as a reusable package and API. Classroom datasets, assignment sheets,
and student analyses are not included and are not covered by this code license.

API implementation references: [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/)
and [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/).
