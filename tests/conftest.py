"""Shared helpers for the tests: small parquet files with known answers."""

import pandas as pd
import pytest

from taxi_revenue import config, pipeline

PICKUP = "lpep_pickup_datetime"
AMOUNT = "total_amount"

# Three staged files with a known answer (used by the pipeline and command line tests).
STAGED_ROWS = {
    "2025-01": [("2025-01-10 10:00", 10.00), ("2025-01-10 11:00", -2.50)],
    "2025-02": [("2025-02-01 00:00", 4.00), ("2025-01-31 23:59", 1.00)],
    "2025-03": [("2025-03-31 12:00", 6.00), ("2025-04-02 08:00", 100.00)],  # 2nd: dropped
}
STAGED_CSV = (
    "service_date,trip_count,daily_revenue\n"
    "2025-01-10,2,7.5\n"
    "2025-01-31,1,1.0\n"
    "2025-02-01,1,4.0\n"
    "2025-03-31,1,6.0\n"
)


@pytest.fixture
def make_parquet(tmp_path):
    """Return a function that writes a small parquet file and gives back its path."""

    def _make(name, rows):
        frame = pd.DataFrame(rows, columns=[PICKUP, AMOUNT])
        frame[PICKUP] = pd.to_datetime(frame[PICKUP])
        frame["trip_distance"] = 1.0  # an extra column the engines must ignore
        path = tmp_path / name
        frame.to_parquet(path, index=False)
        return path

    return _make


@pytest.fixture(params=sorted(pipeline.ENGINES))
def engine(request):
    """Run every test that asks for this once per engine: pandas, polars, duckdb."""
    return pipeline.ENGINES[request.param]


@pytest.fixture
def staged_raw(tmp_path, monkeypatch):
    """Three staged files in a fake project folder. The settings point to that folder."""
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    for month, rows in STAGED_ROWS.items():
        frame = pd.DataFrame(rows, columns=[PICKUP, AMOUNT])
        frame[PICKUP] = pd.to_datetime(frame[PICKUP])
        frame.to_parquet(raw / config.file_name(month), index=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RAW_DIR", raw)
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path / "data" / "processed")
    return raw
