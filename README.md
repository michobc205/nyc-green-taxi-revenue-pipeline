# NYC Green Taxi Revenue Pipeline

Daily revenue for the NYC green taxi trips of January to March 2025, calculated with three tools (pandas, polars and DuckDB) that give exactly the same result.

This is a data pipeline project from my AI engineering training at neuefische. It is a study as well as a project: [results/RESULTS.md](results/RESULTS.md) explains every choice in detail. The slides ([PDF](slides/nyc-green-taxi-revenue-pipeline.pdf), [PowerPoint](slides/nyc-green-taxi-revenue-pipeline.pptx)) are a short summary.

**Contents:** [What it does](#what-it-does) | [Quick start](#quick-start) | [The data and the three rules](#the-data-and-the-three-rules) | [How it works](#how-it-works-extract-transform-load) | [ETL or ELT?](#etl-or-elt) | [The three engines](#the-three-engines) | [The four steps of the brief](#the-four-steps-of-the-brief) | [Project structure](#project-structure) | [Tests](#tests) | [Answers to the three questions](#answers-to-the-three-questions) | [Limits](#limits-and-what-i-did-not-verify) | [Credits and licence](#credits-and-licence)

## What it does

1. Downloads the three monthly files into `data/raw/` (the staging folder). The files stay unchanged.
2. Reads them, applies three rules, and adds up the revenue per pickup day.
3. Writes `daily_revenue.csv`, `daily_revenue.parquet` and `pipeline_metadata.json` into `data/processed/`.

Result on the real data: **146,475 trips on 90 days, total revenue 3,395,290.56** (the sum of `total_amount`, which does not include cash tips).

The result file `data/processed/daily_revenue.csv` starts like this:

~~~
service_date,trip_count,daily_revenue
2025-01-01,1001,25076.51
2025-01-02,1516,34256.83
2025-01-03,1525,36517.69
~~~

## Quick start

You need [uv](https://docs.astral.sh/uv/) 0.13.5 or newer. It installs Python 3.13.17 if needed.

~~~bash
git clone https://github.com/michobc205/nyc-green-taxi-revenue-pipeline.git
cd nyc-green-taxi-revenue-pipeline
uv sync                                    # install everything

uv run taxi-revenue download               # the 3 files go into data/raw
uv run taxi-revenue run                    # calculate with the default engine (pandas)
uv run taxi-revenue run --engine duckdb    # or: --engine polars
uv run taxi-revenue compare                # check the 3 results are identical, and time them
uv run taxi-revenue flow                   # the same pipeline as a Prefect flow (optional)
uv run pytest                              # the tests (about 35 seconds; the first run after a fresh install can take a few minutes)
uv run python experiments/data_profile.py                # the tables behind the data findings (read-only)
uv run python experiments/engine_timing_experiment.py    # why is DuckDB slower? (a minute or so)
~~~

What `run` prints on the real data:

~~~
Engine: pandas
Rows read: 146,486 | used: 146,475 | dropped outside the date window: 11 | dropped for missing values: 0
Kept negative amounts: 478 (sum -6,462.61) | kept zero amounts: 254
Days: 90 | total revenue: 3,395,290.56
Written: data/processed/daily_revenue.csv
Written: data/processed/daily_revenue.parquet
Written: data/processed/pipeline_metadata.json
~~~

The Prefect flow starts a temporary local server (the first start takes 15 to 30 seconds). If you already use Prefect with your own settings, read the note in [results/RESULTS.md](results/RESULTS.md) first.

## The data and the three rules

Before writing any code, I looked at the real files. Each month has 21 columns, and the three files have the same columns. The rules come from what I found:

| Rule | What it does | Why | Real numbers |
|---|---|---|---|
| 1. Date window | Only trips picked up from 1 January up to, but not including, 1 April 2025 count. | The task is three months, and the files hold a few trips from other dates. | 11 trips dropped (6 from December 2024, 5 from April 2025), worth 304.73 in total |
| 2. Keep negative and zero amounts | The result is net revenue. | Negative amounts look like corrections. Removing them would hide real money movements. | 478 negative trips (sum -6,462.61), 254 zero trips, all kept |
| 3. Unusable rows | A trip with no pickup date or no amount is dropped and counted. | A missing amount is unknown, not zero. | 0 trips in this data |

**Money is added in whole cents** (integers), not as decimals. This is why the three tools can give exactly the same number. In this data, no amount has more than two decimals.

## How it works: extract, transform, load

| Stage | What happens | Where |
|---|---|---|
| Extract | Download the files unchanged into the staging folder | `download.py` |
| Transform | Apply the rules and add up per day | `engine_pandas.py`, `engine_polars.py`, `engine_duckdb.py` |
| Load | Write the CSV, the parquet file and the metadata file | `pipeline.py` |

## ETL or ELT?

Both, on purpose.

- **pandas and polars are ETL.** The data is read into Python, transformed in memory, and only the finished result is saved.
- **DuckDB is ELT.** The raw files are first loaded, unchanged, into a database table. Then five SQL steps run inside the database (`raw_trips`, `trips`, `flagged`, `used_trips`, `daily`). The engine function can keep the layers in a database file, to look at them with SQL. This is not offered on the command line, and it has no automated test.
- **The default is pandas (ETL).** It is the simplest to read, and the data is small (146,486 rows).
- ELT would be a better fit when the data is too large for memory, or when the raw data must be kept and asked new questions later. That is general reasoning. I did not test it here.

## The three engines

| Engine | Style | Median time | Result |
|---|---|---|---|
| pandas | ETL | 0.090 s | identical |
| polars | ETL | 0.022 s | identical |
| DuckDB | ELT | 0.131 s (0.045 s as one single query) | identical |

"Identical" is exact: the CSV files of all three engines are the same byte for byte, and the tables are equal without any rounding tolerance.

polars was the fastest. DuckDB, as built, was the slowest: starting a database and loading all 21 columns into a table took 0.068 s of the 0.106 s that its five layers needed (64 percent). One single query straight on the files took 0.045 s. All numbers come from one run on one Windows computer. Differences below about 20 percent are noise. The details are in [results/RESULTS.md](results/RESULTS.md).

## The four steps of the brief

The brief suggests four steps. This is where each one is in this project.

| Step of the brief | What the brief suggests | Where in this project |
|---|---|---|
| 1. Extract | List what the download needs, build each link, save to staging, decide what happens on a second run | `config.py` (host, file names, months, folder) and `download.py` (checks the files, keeps valid ones, `--force` downloads again) |
| 2. Explore | Look at types, missing values and ranges, and note what needs cleaning | `experiments/data_profile.py` (read-only tables) and [section 3 of the study](results/RESULTS.md#3-the-data) |
| 3. Transform and load | Choose ETL or ELT, clean, group by day, sum the revenue, write the result, compare row counts before and after | the three engines, `pipeline.py`, and the metadata file (rows read, used and dropped) |
| 4. Orchestrate (bonus) | The plain pipeline first, then tasks and a flow, with retries | `flow.py`: three tasks, and 2 retries on the download |

## Project structure

~~~
src/taxi_revenue/
  config.py          months, links, folders, date window, column names
  download.py        downloads the files and checks they are real parquet files
  engine_pandas.py   engine 1 (ETL)
  engine_polars.py   engine 2 (ETL, lazy)
  engine_duckdb.py   engine 3 (ELT, SQL)
  pipeline.py        runs one engine and writes the three output files
  compare.py         checks the engines give the same result, and times them
  flow.py            the Prefect flow (optional extension)
  cli.py             the commands: download, run, compare, flow
tests/               89 tests
experiments/         the timing experiment and the data profile (the tables behind RESULTS.md)
results/             RESULTS.md (the long study) and the saved experiment numbers
data/raw/            the downloaded files (not in Git)
data/processed/      the result files (not in Git)
slides/              a short PowerPoint summary
~~~

## Tests

89 tests cover the three engines (the same tests for each), the rules and their edge cases, the download (against a small local test server), the output files, the command line, the Prefect flow, the comparison, the experiment script and the data profile script. To check the tests themselves, the code was deliberately broken in a test copy, for instance with the window end included or decimals added instead of cents, and the tests failed. In three places my first tests missed a broken copy, and I improved the test data (see section 8 of [results/RESULTS.md](results/RESULTS.md)).

## Answers to the three questions

**1. What steps did I take?**
I cloned the template and looked at the real data first. I wrote down three rules, built the download code, and built the same calculation three times (pandas, polars, DuckDB). I proved the results are identical, added the output files, a command line, tests and the Prefect flow, and finally ran an experiment to find out why DuckDB was slower, and took a closer look at the zero amounts.

**2. What challenges did I face?**
The real data had surprises: trips from other months inside a file and hundreds of negative amounts. Getting exactly the same result from three tools was hard because adding decimals can differ in the last digit, so I switched to whole cents. My first equality check was too tolerant, and I only found this when a planted error went unnoticed. On Windows, line endings (CRLF and LF) and an existing Prefect setup needed care. One data problem stays open: one data provider reports a total of 0 on 160 trips that have fare parts (0.02 percent of the total), and I could not find out why.

**3. What would I do differently with more time?**
Test with a full year of data, and measure memory as well as time. Add automatic checks on GitHub for every change. Keep the DuckDB layers in a file and query them. Ask the data provider why vendor 6 trips have a total of 0, and why the totals of vendors 1 and 6 differ from the sum of their parts.

## Limits and what I did not verify

- One Windows computer and 146,486 trips. The timings say nothing about very large data.
- 464 of the 478 negative amounts have payment type 3 (no charge) or 4 (dispute). These meanings come from the official TLC data dictionary (version of 18 March 2025).
- `total_amount` does not include cash tips, so the real revenue can be higher than the number here.
- Most of the March zero amounts come from one data provider (vendor 6: 110 of 147), worth only 0.02 percent of the total. Why it reports a total of 0 is not known.
- The download link comes from the school template. I did not read the terms of use of the data.
- Developed on Windows with Git Bash. The code was also run in a Linux test environment with generated data. It was not tested on macOS.

## Credits and licence

- Built from the neuefische data pipeline project template (MIT licence). The school's reference solution is not part of this repository.
- Data: [NYC Taxi and Limousine Commission trip record data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page). Please check the terms of use yourself.
- Licence: MIT. `LICENSE` keeps the school's copyright notice and adds mine.
