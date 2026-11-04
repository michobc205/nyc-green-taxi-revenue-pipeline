"""Tests for the timing experiment. The experiment repeats some SQL and pandas code on
purpose (to time the steps separately), so these tests make sure the copies still give
exactly the same answer as the engines."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "experiments" / "engine_timing_experiment.py"

# Includes the moments right at the edges of the date window and some unusable trips,
# so a copy with a slightly wrong rule gives a different table.
EDGE_ROWS = [
    ("2024-12-31 23:59:59", 1.00),
    ("2025-01-01 00:00:00", 2.00),
    ("2025-02-14 12:00:00", -3.50),
    ("2025-02-14 13:00:00", 0.00),
    ("2025-03-31 23:59:59", 3.00),
    ("2025-04-01 00:00:00", 4.00),
    (None, 5.00),
    ("2025-02-01 09:00:00", None),
]


@pytest.fixture(scope="module")
def experiment():
    spec = importlib.util.spec_from_file_location("engine_timing_experiment", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paths(make_parquet):
    return [make_parquet("edges.parquet", EDGE_ROWS)]


def test_all_variants_give_exactly_the_same_table(experiment, paths):
    assert experiment.check_identical(paths) == []


def test_the_check_notices_a_wrong_variant(experiment, paths, monkeypatch):
    def wrong(files):
        table = experiment.pandas_as_built(files).copy()
        table.loc[0, "daily_revenue"] += 1e-9  # one billionth: only an exact check sees it
        return table

    monkeypatch.setitem(experiment.END_TO_END, "a wrong variant", wrong)
    assert experiment.check_identical(paths) == ["a wrong variant"]


def test_the_duckdb_layers_are_timed_one_by_one(experiment, paths):
    steps = experiment.duckdb_layer_seconds(paths)
    assert len(steps) == 7
    assert all(seconds >= 0 for seconds in steps.values())


def test_reading_only_functions_run(experiment, paths):
    for function in experiment.READ_ONLY.values():
        function(paths)
