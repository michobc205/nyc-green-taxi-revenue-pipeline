"""Engine 3: DuckDB (ELT style, SQL).

ELT means: Extract and Load first, Transform afterwards, inside the database.
  1. raw_trips   the parquet files, loaded as they are (all columns)
  2. trips       the two needed columns with clean types
  3. flagged     every trip marked: has values? inside the date window?
  4. used_trips  only the trips that count, with the amount in whole cents
  5. daily       one row per day

By default the database lives in memory and disappears at the end. Give a file
name as database to keep the tables and look at every step with SQL later.
Money is added up in whole cents, exactly like in the other two engines.
"""

from collections.abc import Iterable
from pathlib import Path

import duckdb
import pandas as pd

from taxi_revenue import config

ENGINE_NAME = "duckdb"


def calculate(
    paths: Iterable[Path], database: str = ":memory:"
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Calculate the daily revenue from the given parquet files."""
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError("No input files were given.")

    # The names below come from config.py (never from a user), so they are safe in SQL.
    pickup_col = f'"{config.PICKUP_COLUMN}"'
    amount_col = f'"{config.AMOUNT_COLUMN}"'
    start = f"TIMESTAMP '{config.WINDOW_START}'"
    end = f"TIMESTAMP '{config.WINDOW_END}'"

    con = duckdb.connect(database)
    try:
        for path in paths:
            described = con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [path.as_posix()]
            ).fetchall()
            names = {row[0] for row in described}
            missing = [c for c in (config.PICKUP_COLUMN, config.AMOUNT_COLUMN) if c not in names]
            if missing:
                raise ValueError(f"{path.name} is missing the column(s): {missing}")

        # E + L: copy the raw files into a table, unchanged.
        con.execute(
            "CREATE OR REPLACE TABLE raw_trips AS "
            "SELECT * FROM read_parquet(?, union_by_name = true)",
            [[path.as_posix() for path in paths]],
        )

        # T: everything below is SQL inside the database.
        con.execute(f"""
            CREATE OR REPLACE TABLE trips AS
            SELECT CAST({pickup_col} AS TIMESTAMP) AS pickup,
                   TRY_CAST({amount_col} AS DOUBLE) AS amount
            FROM raw_trips
        """)
        con.execute(f"""
            CREATE OR REPLACE TABLE flagged AS
            SELECT pickup, amount,
                   -- Rule 3: no pickup date or no amount means the trip cannot be used.
                   COALESCE(pickup IS NOT NULL AND amount IS NOT NULL
                            AND NOT isnan(amount), FALSE) AS has_values,
                   -- Rule 1: only trips picked up inside the date window count.
                   COALESCE(pickup >= {start} AND pickup < {end}, FALSE) AS in_window
            FROM trips
        """)
        con.execute("""
            CREATE OR REPLACE TABLE used_trips AS
            SELECT strftime(pickup, '%Y-%m-%d') AS service_date,
                   amount,
                   CAST(round(amount * 100) AS BIGINT) AS cents
            FROM flagged
            WHERE has_values AND in_window
        """)
        con.execute("""
            CREATE OR REPLACE TABLE daily AS
            SELECT service_date,
                   CAST(count(*) AS BIGINT) AS trip_count,
                   CAST(sum(cents) AS BIGINT) AS total_cents,
                   round(sum(cents) / 100.0, 2) AS daily_revenue
            FROM used_trips
            GROUP BY service_date
        """)

        table = con.execute(
            "SELECT service_date, trip_count, daily_revenue FROM daily ORDER BY service_date"
        ).df()
        table["service_date"] = table["service_date"].astype("str")

        read, missing, outside = con.execute("""
            SELECT count(*),
                   count(*) FILTER (WHERE NOT has_values),
                   count(*) FILTER (WHERE has_values AND NOT in_window)
            FROM flagged
        """).fetchall()[0]
        used, negative, negative_cents, zero, off_cents, total_cents = con.execute("""
            SELECT count(*),
                   count(*) FILTER (WHERE amount < 0),
                   coalesce(sum(cents) FILTER (WHERE cents < 0), 0),
                   count(*) FILTER (WHERE amount = 0),
                   count(*) FILTER (WHERE abs(amount * 100 - round(amount * 100)) > 1e-6),
                   coalesce(sum(cents), 0)
            FROM used_trips
        """).fetchall()[0]
    finally:
        con.close()

    metadata: dict[str, object] = {
        "engine": ENGINE_NAME,
        "rows_read": int(read),
        "rows_dropped_missing_values": int(missing),
        "rows_dropped_outside_window": int(outside),
        "rows_used": int(used),
        # Rule 2: negative and zero amounts are kept, but counted.
        "negative_amount_trips": int(negative),
        "negative_amount_sum": round(float(negative_cents) / 100, 2),
        "zero_amount_trips": int(zero),
        # Must be 0, otherwise adding in whole cents would change the result.
        "amounts_not_in_whole_cents": int(off_cents),
        "days_in_output": int(len(table)),
        "revenue_total": round(float(total_cents) / 100, 2),
    }
    return table, metadata
