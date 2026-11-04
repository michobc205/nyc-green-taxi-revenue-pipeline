"""Timing experiment: why is one engine slower than another?

In the normal comparison (taxi-revenue compare) DuckDB was the slowest engine. This
script tests three possible reasons, one at a time, instead of guessing:

  Part 1  Only reading the files, with no calculation: all columns or only the two we need.
  Part 2  The whole calculation: the engines as built, plus two variants.
            - pandas that reads only the 2 columns it needs
            - DuckDB with one single query straight on the files (no 5 table layers)
  Part 3  The 5 DuckDB layers, timed one by one.

Before any timing, the script checks that all variants give exactly the same table.
A faster variant that gives a different answer would be worthless.

Run it from the project folder:
    uv run python experiments/engine_timing_experiment.py --repeats 7 --save
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from importlib.metadata import version

import duckdb
import pandas as pd
import polars as pl

from taxi_revenue import config, engine_duckdb, engine_pandas, engine_polars, pipeline

NEEDED = [config.PICKUP_COLUMN, config.AMOUNT_COLUMN]
PICKUP = f'"{config.PICKUP_COLUMN}"'
AMOUNT = f'"{config.AMOUNT_COLUMN}"'
START = f"TIMESTAMP '{config.WINDOW_START}'"
END = f"TIMESTAMP '{config.WINDOW_END}'"


# ----------------------------------------------------------------------------------
# Part 1: only reading the files
# ----------------------------------------------------------------------------------
def read_pandas_all_columns(paths):
    for path in paths:
        pd.read_parquet(path)


def read_pandas_two_columns(paths):
    for path in paths:
        pd.read_parquet(path, columns=NEEDED)


def read_polars_all_columns(paths):
    for path in paths:
        pl.read_parquet(path)


def read_polars_two_columns(paths):
    for path in paths:
        pl.read_parquet(path, columns=NEEDED)


def _duckdb_load(paths, select):
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TABLE loaded AS SELECT {select} FROM read_parquet(?, union_by_name = true)",
            [[path.as_posix() for path in paths]],
        )
    finally:
        con.close()


def read_duckdb_all_columns(paths):
    _duckdb_load(paths, "*")


def read_duckdb_two_columns(paths):
    _duckdb_load(paths, f"{PICKUP}, {AMOUNT}")


READ_ONLY = {
    "pandas, all columns": read_pandas_all_columns,
    "pandas, 2 columns": read_pandas_two_columns,
    "polars, all columns": read_polars_all_columns,
    "polars, 2 columns": read_polars_two_columns,
    "duckdb, all columns (into a table)": read_duckdb_all_columns,
    "duckdb, 2 columns (into a table)": read_duckdb_two_columns,
}


# ----------------------------------------------------------------------------------
# Part 2: the whole calculation (only the result table, same rules as the engines)
# ----------------------------------------------------------------------------------
def pandas_as_built(paths):
    return engine_pandas.calculate(paths)[0]


def pandas_two_columns(paths):
    trips = pd.concat([pd.read_parquet(p, columns=NEEDED) for p in paths], ignore_index=True)
    pickup = pd.to_datetime(trips[config.PICKUP_COLUMN], errors="coerce")
    amount = pd.to_numeric(trips[config.AMOUNT_COLUMN], errors="coerce")
    keep = (
        pickup.notna()
        & amount.notna()
        & (pickup >= config.WINDOW_START)
        & (pickup < config.WINDOW_END)
    )
    cents = (amount[keep] * 100).round().astype("int64")
    table = (
        pd.DataFrame({"service_date": pickup[keep].dt.strftime("%Y-%m-%d"), "cents": cents})
        .groupby("service_date", as_index=False)
        .agg(trip_count=("cents", "size"), total_cents=("cents", "sum"))
        .sort_values("service_date", ignore_index=True)
    )
    table["daily_revenue"] = (table["total_cents"] / 100).round(2)
    return table[["service_date", "trip_count", "daily_revenue"]]


def polars_as_built(paths):
    return engine_polars.calculate(paths)[0]


def duckdb_as_built(paths):
    return engine_duckdb.calculate(paths)[0]


def duckdb_one_query(paths):
    con = duckdb.connect()
    try:
        table = con.execute(
            f"""
            WITH trips AS (
                SELECT CAST({PICKUP} AS TIMESTAMP) AS pickup,
                       TRY_CAST({AMOUNT} AS DOUBLE) AS amount
                FROM read_parquet(?, union_by_name = true)
            )
            SELECT strftime(pickup, '%Y-%m-%d') AS service_date,
                   CAST(count(*) AS BIGINT) AS trip_count,
                   round(sum(CAST(round(amount * 100) AS BIGINT)) / 100.0, 2) AS daily_revenue
            FROM trips
            WHERE pickup IS NOT NULL AND amount IS NOT NULL AND NOT isnan(amount)
              AND pickup >= {START} AND pickup < {END}
            GROUP BY service_date
            ORDER BY service_date
            """,
            [[path.as_posix() for path in paths]],
        ).df()
    finally:
        con.close()
    table["service_date"] = table["service_date"].astype("str")
    return table


END_TO_END = {
    "pandas as built (reads all columns)": pandas_as_built,
    "pandas, reads only the 2 columns": pandas_two_columns,
    "polars as built (lazy, 2 columns)": polars_as_built,
    "duckdb as built (5 table layers)": duckdb_as_built,
    "duckdb, one query on the files": duckdb_one_query,
}


def check_identical(paths):
    """Return the names of the variants whose table is NOT exactly equal to pandas as built."""
    reference = pandas_as_built(paths)
    different = []
    for name, function in END_TO_END.items():
        try:
            pd.testing.assert_frame_equal(reference, function(paths), check_exact=True)
        except AssertionError:
            different.append(name)
    return different


# ----------------------------------------------------------------------------------
# Part 3: the DuckDB layers, one by one (same SQL as engine_duckdb.py)
# ----------------------------------------------------------------------------------
def duckdb_layer_seconds(paths):
    """Run the DuckDB engine step by step once and return {step: seconds}."""
    steps = {}

    def run(name, function):
        started = time.perf_counter()
        function()
        steps[name] = time.perf_counter() - started

    holder = {}
    run("0 start the database", lambda: holder.update(con=duckdb.connect()))
    con = holder["con"]
    try:
        run("1 raw_trips: load the files, all columns", lambda: con.execute(
            "CREATE TABLE raw_trips AS SELECT * FROM read_parquet(?, union_by_name = true)",
            [[path.as_posix() for path in paths]]))
        run("2 trips: 2 columns, clean types", lambda: con.execute(
            f"CREATE TABLE trips AS SELECT CAST({PICKUP} AS TIMESTAMP) AS pickup, "
            f"TRY_CAST({AMOUNT} AS DOUBLE) AS amount FROM raw_trips"))
        run("3 flagged: mark every trip", lambda: con.execute(
            f"""CREATE TABLE flagged AS SELECT pickup, amount,
                COALESCE(pickup IS NOT NULL AND amount IS NOT NULL AND NOT isnan(amount), FALSE) AS has_values,
                COALESCE(pickup >= {START} AND pickup < {END}, FALSE) AS in_window FROM trips"""))
        run("4 used_trips: keep the trips that count", lambda: con.execute(
            """CREATE TABLE used_trips AS SELECT strftime(pickup, '%Y-%m-%d') AS service_date,
                amount, CAST(round(amount * 100) AS BIGINT) AS cents
                FROM flagged WHERE has_values AND in_window"""))
        run("5 daily: one row per day", lambda: con.execute(
            """CREATE TABLE daily AS SELECT service_date, CAST(count(*) AS BIGINT) AS trip_count,
                CAST(sum(cents) AS BIGINT) AS total_cents, round(sum(cents) / 100.0, 2) AS daily_revenue
                FROM used_trips GROUP BY service_date"""))
        run("6 read the table and the counts out", lambda: (
            con.execute("SELECT service_date, trip_count, daily_revenue FROM daily ORDER BY service_date").df(),
            con.execute("SELECT count(*), count(*) FILTER (WHERE NOT has_values) FROM flagged").fetchall(),
            con.execute("SELECT count(*), sum(cents) FROM used_trips").fetchall()))
    finally:
        con.close()
    return steps


# ----------------------------------------------------------------------------------
# Measuring and reporting
# ----------------------------------------------------------------------------------
def measure(function, repeats):
    """One warm-up run, then `repeats` timed runs. Returns (median, fastest, slowest)."""
    function()
    seconds = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        seconds.append(time.perf_counter() - started)
    return statistics.median(seconds), min(seconds), max(seconds)


def print_table(title, rows):
    print(f"\n{title}")
    width = max(len(name) for name in rows) + 2
    print(f"{'':<{width}}{'median (s)':>12}{'fastest (s)':>13}{'slowest (s)':>13}")
    for name, (median, fastest, slowest) in rows.items():
        print(f"{name:<{width}}{median:>12.3f}{fastest:>13.3f}{slowest:>13.3f}")


def run_experiment(paths, repeats):
    different = check_identical(paths)
    if different:
        print("STOP: these variants do not give the same table as pandas as built:")
        for name in different:
            print("  -", name)
        raise SystemExit(1)
    print(f"Check passed: all {len(END_TO_END)} variants give exactly the same table.")

    read_only = {name: measure(lambda f=f: f(paths), repeats) for name, f in READ_ONLY.items()}
    end_to_end = {name: measure(lambda f=f: f(paths), repeats) for name, f in END_TO_END.items()}

    duckdb_layer_seconds(paths)  # warm-up
    runs = [duckdb_layer_seconds(paths) for _ in range(repeats)]
    layers = {
        name: (
            statistics.median(run[name] for run in runs),
            min(run[name] for run in runs),
            max(run[name] for run in runs),
        )
        for name in runs[0]
    }

    print_table("Part 1: only reading the files (no calculation)", read_only)
    print_table("Part 2: the whole calculation", end_to_end)
    print_table("Part 3: the DuckDB layers, one by one", layers)
    total = sum(median for median, _, _ in layers.values())
    print(f"{'(sum of the layer medians)':<44}{total:>12.3f}")
    print(f"\n(each line: 1 warm-up run, then {repeats} timed runs)")

    rows_read = int(engine_pandas.calculate(paths)[1]["rows_read"])
    return {
        "environment": {
            "system": platform.system(),
            "python": platform.python_version(),
            "pandas": version("pandas"),
            "polars": version("polars"),
            "duckdb": version("duckdb"),
            "cpu_count": os.cpu_count(),
        },
        "data": {
            "rows_read": rows_read,
            "files": {path.name: path.stat().st_size for path in paths},
        },
        "repeats": repeats,
        "all_variants_identical": True,
        "part_1_reading_only": {n: dict(zip(("median", "fastest", "slowest"), v)) for n, v in read_only.items()},
        "part_2_whole_calculation": {n: dict(zip(("median", "fastest", "slowest"), v)) for n, v in end_to_end.items()},
        "part_3_duckdb_layers": {n: dict(zip(("median", "fastest", "slowest"), v)) for n, v in layers.items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Timing experiment for the three engines.")
    parser.add_argument("--repeats", type=int, default=7, help="timed runs per line (default 7)")
    parser.add_argument("--save", action="store_true", help="write results/engine_timing_experiment.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    paths = pipeline.raw_paths()
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        sys.exit(f"Missing staged file(s): {missing}. Run: uv run taxi-revenue download")

    result = run_experiment(paths, args.repeats)
    if args.save:
        target = config.PROJECT_ROOT / "results" / "engine_timing_experiment.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Saved: {target.relative_to(config.PROJECT_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
