"""Engine 1: pandas (ETL style).

The files are read into Python, transformed in memory, and only the finished
result leaves this module. Money is added up in whole cents, so the sum is exact
and the other two engines can reach the identical number.

The result of every engine has the same shape:
  table     one row per day: service_date, trip_count, daily_revenue
  metadata  a dictionary of counts that explain what happened to the rows
"""

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from taxi_revenue import config

ENGINE_NAME = "pandas"


def calculate(paths: Iterable[Path]) -> tuple[pd.DataFrame, dict[str, object]]:
    """Calculate the daily revenue from the given parquet files."""
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError("No input files were given.")

    needed = [config.PICKUP_COLUMN, config.AMOUNT_COLUMN]
    parts = []
    for path in paths:
        trips = pd.read_parquet(path)
        missing = [name for name in needed if name not in trips.columns]
        if missing:
            raise ValueError(f"{path.name} is missing the column(s): {missing}")
        parts.append(trips[needed])
    trips = pd.concat(parts, ignore_index=True)
    rows_read = len(trips)

    pickup = pd.to_datetime(trips[config.PICKUP_COLUMN], errors="coerce")
    amount = pd.to_numeric(trips[config.AMOUNT_COLUMN], errors="coerce")

    # Rule 3: a trip without a pickup date or without an amount cannot be used.
    has_values = pickup.notna() & amount.notna()
    # Rule 1: only trips picked up inside the date window count.
    in_window = (pickup >= config.WINDOW_START) & (pickup < config.WINDOW_END)
    used = has_values & in_window

    pickup = pickup[used]
    amount = amount[used]
    cents = (amount * 100).round().astype("int64")

    table = (
        pd.DataFrame({"service_date": pickup.dt.strftime("%Y-%m-%d"), "cents": cents})
        .groupby("service_date", as_index=False)
        .agg(trip_count=("cents", "size"), total_cents=("cents", "sum"))
        .sort_values("service_date", ignore_index=True)
    )
    table["daily_revenue"] = (table["total_cents"] / 100).round(2)
    table = table[["service_date", "trip_count", "daily_revenue"]]

    metadata: dict[str, object] = {
        "engine": ENGINE_NAME,
        "rows_read": int(rows_read),
        "rows_dropped_missing_values": int((~has_values).sum()),
        "rows_dropped_outside_window": int((has_values & ~in_window).sum()),
        "rows_used": int(used.sum()),
        # Rule 2: negative and zero amounts are kept, but counted.
        "negative_amount_trips": int((amount < 0).sum()),
        "negative_amount_sum": round(float(cents[cents < 0].sum()) / 100, 2),
        "zero_amount_trips": int((amount == 0).sum()),
        # Must be 0, otherwise adding in whole cents would change the result.
        "amounts_not_in_whole_cents": int(
            ((amount * 100 - (amount * 100).round()).abs() > 1e-6).sum()
        ),
        "days_in_output": int(len(table)),
        "revenue_total": round(float(cents.sum()) / 100, 2),
    }
    return table, metadata
