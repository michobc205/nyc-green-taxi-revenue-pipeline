"""Tests for the three engines. Every test runs once per engine (see conftest.py)."""

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from taxi_revenue import pipeline

JANUARY = [
    ("2025-01-01 10:00", 10.10),
    ("2025-01-01 23:59", 5.20),
    ("2025-01-02 00:00", 7.00),
    ("2024-12-31 23:59", 99.00),  # before the window: dropped
    ("2025-01-02 12:00", -3.50),  # negative: kept
    ("2025-01-02 13:00", 0.00),  # zero: kept
    (None, 4.00),  # no pickup date: dropped
    ("2025-01-03 09:00", None),  # no amount: dropped
]
MARCH = [
    ("2025-03-31 23:59", 1.15),
    ("2025-04-01 00:00", 50.00),  # after the window: dropped
    ("2025-01-01 08:00", 0.10),  # a January trip inside another file: kept
]


def test_known_answer(engine, make_parquet):
    paths = [make_parquet("jan.parquet", JANUARY), make_parquet("mar.parquet", MARCH)]
    table, meta = engine.calculate(paths)

    assert table["service_date"].tolist() == ["2025-01-01", "2025-01-02", "2025-03-31"]
    assert table["trip_count"].tolist() == [3, 3, 1]
    assert table["daily_revenue"].tolist() == [15.40, 3.50, 1.15]
    assert meta["rows_read"] == 11
    assert meta["rows_dropped_missing_values"] == 2
    assert meta["rows_dropped_outside_window"] == 2
    assert meta["rows_used"] == 7
    assert meta["negative_amount_trips"] == 1
    assert meta["negative_amount_sum"] == -3.50
    assert meta["zero_amount_trips"] == 1
    assert meta["amounts_not_in_whole_cents"] == 0
    assert meta["days_in_output"] == 3
    assert meta["revenue_total"] == 20.05


def test_table_has_the_agreed_shape(engine, make_parquet):
    table, _ = engine.calculate([make_parquet("jan.parquet", JANUARY)])
    assert list(table.columns) == ["service_date", "trip_count", "daily_revenue"]
    assert table["trip_count"].dtype == "int64"
    assert table["daily_revenue"].dtype == "float64"
    assert table["service_date"].is_monotonic_increasing


def test_window_edges(engine, make_parquet):
    """The start moment is inside the window, the end moment is outside."""
    rows = [
        ("2024-12-31 23:59:59", 1.00),
        ("2025-01-01 00:00:00", 2.00),
        ("2025-03-31 23:59:59", 3.00),
        ("2025-04-01 00:00:00", 4.00),
    ]
    table, meta = engine.calculate([make_parquet("edges.parquet", rows)])
    assert table["service_date"].tolist() == ["2025-01-01", "2025-03-31"]
    assert meta["revenue_total"] == 5.00
    assert meta["rows_dropped_outside_window"] == 2


def test_negative_and_zero_amounts_are_kept(engine, make_parquet):
    rows = [("2025-02-10 08:00", -10.00), ("2025-02-10 09:00", 0.00), ("2025-02-10 10:00", 5.00)]
    table, meta = engine.calculate([make_parquet("net.parquet", rows)])
    assert table["trip_count"].tolist() == [3]
    assert table["daily_revenue"].tolist() == [-5.00]
    assert meta["negative_amount_trips"] == 1
    assert meta["negative_amount_sum"] == -10.00
    assert meta["zero_amount_trips"] == 1


def test_a_real_nan_amount_is_dropped_like_an_empty_one(engine, tmp_path):
    """NaN (not a number) is different from empty (null). Both mean: no amount."""
    stamps = pd.to_datetime(["2025-02-01 10:00", "2025-02-01 11:00", "2025-02-02 09:00"])
    table = pa.table(
        {
            "lpep_pickup_datetime": pa.array(stamps, type=pa.timestamp("us")),
            "total_amount": pa.array([5.0, float("nan"), 2.5]),
        }
    )
    path = tmp_path / "nan.parquet"
    pq.write_table(table, path)
    result, meta = engine.calculate([path])
    assert result["trip_count"].tolist() == [1, 1]
    assert meta["rows_dropped_missing_values"] == 1
    assert meta["revenue_total"] == 7.5


def test_the_same_day_in_two_files_is_added_up(engine, make_parquet):
    first = make_parquet("a.parquet", [("2025-02-05 10:00", 1.00), ("2025-02-05 11:00", 2.00)])
    second = make_parquet("b.parquet", [("2025-02-05 12:00", 4.00)])
    table, _ = engine.calculate([first, second])
    assert table["trip_count"].tolist() == [3]
    assert table["daily_revenue"].tolist() == [7.00]


def test_money_is_added_exactly(engine, make_parquet):
    """Adding 0.1 and 0.2 as decimals gives 0.30000000000000004. In cents it is exact."""
    rows = [("2025-02-05 10:00", 0.10), ("2025-02-05 11:00", 0.20)]
    table, meta = engine.calculate([make_parquet("cents.parquet", rows)])
    assert table["daily_revenue"].tolist() == [0.3]
    assert meta["revenue_total"] == 0.3


def test_no_files_is_an_error(engine):
    with pytest.raises(ValueError, match="No input files"):
        engine.calculate([])


def test_a_missing_column_is_an_error(engine, tmp_path):
    path = tmp_path / "wrong.parquet"
    pd.DataFrame({"something_else": [1, 2]}).to_parquet(path)
    with pytest.raises(ValueError, match="missing the column"):
        engine.calculate([path])


def test_all_engines_give_exactly_the_same_result(tmp_path):
    """150,000 random trips with decimals, empty values and out-of-window dates."""
    rng = np.random.default_rng(42)
    paths = []
    for number in range(3):
        size = 50_000
        stamps = pd.Timestamp("2024-12-20") + pd.to_timedelta(
            rng.integers(0, 110 * 86400, size), unit="s"
        )
        amounts = np.round(rng.normal(20, 15, size), 2)
        amounts[rng.random(size) < 0.001] = np.nan
        frame = pd.DataFrame({"lpep_pickup_datetime": stamps, "total_amount": amounts})
        frame.loc[rng.random(size) < 0.0005, "lpep_pickup_datetime"] = pd.NaT
        path = tmp_path / f"random_{number}.parquet"
        frame.to_parquet(path, index=False)
        paths.append(path)

    results = {name: module.calculate(paths) for name, module in pipeline.ENGINES.items()}
    base_table, base_meta = results["pandas"]
    base_meta = {key: value for key, value in base_meta.items() if key != "engine"}
    for name, (table, meta) in results.items():
        pd.testing.assert_frame_equal(base_table, table, check_exact=True)
        assert {key: value for key, value in meta.items() if key != "engine"} == base_meta
