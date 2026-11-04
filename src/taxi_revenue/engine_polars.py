"""Engine 2: polars (ETL style, lazy).

polars builds a plan first (scan_parquet is lazy) and runs it only when
collect() is called. The calculation is done inside polars; the finished table
is handed back as a pandas table, so all three engines can be compared directly.

Money is added up in whole cents, exactly like in the pandas engine.
"""

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import pandas as pd
import polars as pl

from taxi_revenue import config

ENGINE_NAME = "polars"


def calculate(paths: Iterable[Path]) -> tuple[pd.DataFrame, dict[str, object]]:
    """Calculate the daily revenue from the given parquet files."""
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError("No input files were given.")

    needed = [config.PICKUP_COLUMN, config.AMOUNT_COLUMN]
    plans = []
    for path in paths:
        missing = [name for name in needed if name not in pl.read_parquet_schema(path)]
        if missing:
            raise ValueError(f"{path.name} is missing the column(s): {missing}")
        plans.append(pl.scan_parquet(path).select(needed))

    window_start = datetime.fromisoformat(config.WINDOW_START)
    window_end = datetime.fromisoformat(config.WINDOW_END)

    pickup = pl.col(config.PICKUP_COLUMN).cast(pl.Datetime("us"), strict=False)
    amount = pl.col(config.AMOUNT_COLUMN).cast(pl.Float64, strict=False)

    trips = (
        pl.concat(plans)
        .select(pickup.alias("pickup"), amount.alias("amount"))
        .with_columns(
            # Rule 3: no pickup date or no amount means the trip cannot be used.
            has_values=(
                pl.col("pickup").is_not_null()
                & pl.col("amount").is_not_null()
                & pl.col("amount").is_not_nan()
            ),
            # Rule 1: only trips picked up inside the date window count.
            in_window=(
                (pl.col("pickup") >= window_start) & (pl.col("pickup") < window_end)
            ).fill_null(False),
        )
        .with_columns(used=pl.col("has_values") & pl.col("in_window"))
    )

    counts = trips.select(
        rows_read=pl.len(),
        missing=(~pl.col("has_values")).sum(),
        outside=(pl.col("has_values") & ~pl.col("in_window")).sum(),
    ).collect()

    used = (
        trips.filter(pl.col("used"))
        .with_columns(
            cents=(pl.col("amount") * 100).round(0).cast(pl.Int64),
            service_date=pl.col("pickup").dt.strftime("%Y-%m-%d"),
        )
        .collect()
    )

    table = (
        used.group_by("service_date")
        .agg(
            trip_count=pl.len().cast(pl.Int64),
            total_cents=pl.col("cents").sum(),
        )
        .sort("service_date")
        .with_columns(daily_revenue=(pl.col("total_cents") / 100).round(2))
        .select("service_date", "trip_count", "daily_revenue")
        .to_pandas()
    )

    cents = used["cents"]
    off_cents = (pl.col("amount") * 100 - (pl.col("amount") * 100).round(0)).abs()
    metadata: dict[str, object] = {
        "engine": ENGINE_NAME,
        "rows_read": int(counts["rows_read"][0]),
        "rows_dropped_missing_values": int(counts["missing"][0]),
        "rows_dropped_outside_window": int(counts["outside"][0]),
        "rows_used": int(used.height),
        # Rule 2: negative and zero amounts are kept, but counted.
        "negative_amount_trips": int((used["amount"] < 0).sum()),
        "negative_amount_sum": round(float(cents.filter(cents < 0).sum()) / 100, 2),
        "zero_amount_trips": int((used["amount"] == 0).sum()),
        # Must be 0, otherwise adding in whole cents would change the result.
        "amounts_not_in_whole_cents": int(
            used.select((off_cents > 1e-6).sum()).item()
        ),
        "days_in_output": int(table.shape[0]),
        "revenue_total": round(float(cents.sum()) / 100, 2),
    }
    return table, metadata
