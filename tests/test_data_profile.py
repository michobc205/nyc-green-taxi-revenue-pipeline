"""Tests for the data profile script, on a small hand-made dataset with known answers."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from taxi_revenue import config, pipeline

SCRIPT = Path(__file__).resolve().parents[1] / "experiments" / "data_profile.py"

# vendor, pickup, amount, payment_type, fare_amount, extra
JANUARY = [
    (1, "2025-01-05 10:00", 10.0, 1.0, 10.0, 0.0),
    (1, "2024-12-31 23:00", 5.0, 1.0, 5.0, 0.0),  # before the window
    (1, "2025-01-06 09:00", -2.0, 3.0, 0.0, 0.0),  # negative
    (2, "2025-01-07 09:00", 0.0, 1.0, 0.0, 0.0),  # zero, parts are zero too
    (2, "2025-02-01 08:00", 4.0, 2.0, 0.0, 0.0),  # February trip inside the January file
]
FEBRUARY = [
    (6, "2025-02-10 09:00", 0.0, None, 3.5, 0.0),  # zero total, but parts above 0
    (6, "2025-02-11 09:00", 0.0, None, 2.0, 0.0),
    (2, "2025-02-12 09:00", 6.0, 1.0, 5.0, 1.0),  # total equals the parts
    (2, "2025-02-13 09:00", 5.1, 1.0, 5.0, 0.0),  # total differs from the parts by 0.10
]
MARCH = [
    (6, "2025-03-20 09:00", 0.0, None, 1.25, 0.0),
    (1, "2025-03-20 10:00", 0.0, 1.0, 0.0, 0.0),
    (2, "2025-04-01 00:00", 9.0, 1.0, 9.0, 0.0),  # after the window
    (2, "2025-03-31 09:00", 7.0, 1.0, 7.0, 0.0),
    (1, "2025-03-25 09:00", 0.0, 1.0, -1.0, 0.0),  # zero total, but the parts are negative
]


@pytest.fixture(scope="module")
def profile():
    spec = importlib.util.spec_from_file_location("data_profile", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def raw_files(tmp_path, monkeypatch):
    """Write the three hand-made files with the real file names and point the settings there."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for month, rows in zip(config.MONTHS, (JANUARY, FEBRUARY, MARCH)):
        frame = pd.DataFrame(rows, columns=["VendorID", "lpep_pickup_datetime", "total_amount", "payment_type", "fare_amount", "extra"])
        frame["lpep_pickup_datetime"] = pd.to_datetime(frame["lpep_pickup_datetime"])
        frame["trip_distance"] = 1.0
        frame.to_parquet(raw / config.file_name(month), index=False)
    monkeypatch.setattr(config, "RAW_DIR", raw)
    return raw


@pytest.fixture
def trips(profile, raw_files):
    return profile.load_trips(pipeline.raw_paths())


def test_month_table(profile, trips):
    table = profile.month_table(trips)
    assert table.loc["Trips"].tolist() == [5, 4, 5]
    assert table.loc["Pickup before the window start"].tolist() == [1, 0, 0]
    assert table.loc["Pickup on or after the window end"].tolist() == [0, 0, 1]
    assert table.loc["Negative amount"].tolist() == [1, 0, 0]
    assert table.loc["Zero amount"].tolist() == [1, 2, 3]
    assert table.loc["Sum of the negative amounts"].tolist() == [-2.0, 0.0, 0.0]
    assert table.loc["Pickup outside the file's own month"].tolist() == [2, 0, 1]


def test_outside_the_window(profile, trips):
    by_month, count, worth = profile.outside_window(trips)
    assert count == 2
    assert worth == 14.0  # 5.0 and 9.0
    assert by_month.to_dict() == {"2024-12": 1, "2025-04": 1}


def test_payment_types(profile, trips):
    negative = profile.payment_types(trips, trips["amount"] < 0)
    assert negative.loc["3", "2025-01"] == 1
    zero = profile.payment_types(trips, trips["amount"] == 0)
    assert zero.loc["empty", "2025-02"] == 2 and zero.loc["empty", "2025-03"] == 1


def test_vendor_tables(profile, trips):
    zero = profile.vendor_zero_table(trips)
    assert zero["zero_total"].to_dict() == {1: 2, 2: 1, 6: 3}
    equal = profile.parts_equal_table(trips)
    assert equal.loc[1, "trips"] == 2 and equal.loc[1, "equal"] == 1
    assert equal.loc[2, "trips"] == 4 and equal.loc[2, "equal"] == 2
    assert 6 not in equal.index  # every vendor 6 total is zero
    parts = profile.zero_parts_table(trips)
    assert parts.loc[6, "parts_above_0"] == 3 and parts.loc[6, "sum_of_parts"] == 6.75
    assert parts.loc[1, "parts_above_0"] == 0


def test_impact_and_days(profile, trips):
    assert profile.impact(trips) == (30.1, 6.75, 36.85)
    assert dict(profile.zero_days(trips)["2025-03"]) == {"2025-03-20": 2, "2025-03-25": 1}


def test_main_prints_every_section(profile, raw_files, capsys):
    profile.main()
    output = capsys.readouterr().out
    for heading in ("3.1", "3.2", "3.3", "3.4", "3.5 A", "3.5 B", "3.5 C", "3.5 D", "3.5 E", "3.6"):
        assert f"--- {heading}" in output
