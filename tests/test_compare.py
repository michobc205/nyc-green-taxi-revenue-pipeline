"""Tests for compare.py: do the engines give the same result, and how fast are they?"""

import pytest

from taxi_revenue import compare, pipeline


def _polars_with_error(error):
    """An engine that behaves like polars, but adds a small error to the first day."""

    class Wrong:
        @staticmethod
        def calculate(paths):
            table, metadata = pipeline.engine_polars.calculate(paths)
            table = table.copy()
            table.loc[0, "daily_revenue"] += error
            return table, metadata

    return Wrong


def test_identical_results_are_reported(staged_raw):
    result = compare.compare(repeats=1)
    assert result.identical
    assert result.differences == []
    assert [timing.engine for timing in result.timings] == list(pipeline.ENGINES)
    assert all(len(timing.seconds) == 1 for timing in result.timings)
    assert (result.rows_used, result.days, result.revenue_total) == (5, 4, 18.5)


def test_a_difference_of_one_billionth_is_noticed(staged_raw, monkeypatch):
    """The first version of the check let tiny differences pass. This one must not."""
    monkeypatch.setitem(pipeline.ENGINES, "polars", _polars_with_error(1e-9))
    result = compare.compare(repeats=1)
    assert not result.identical
    assert "polars table differs from pandas" in result.differences[0]


def test_different_metadata_is_noticed(staged_raw, monkeypatch):
    class WrongMetadata:
        @staticmethod
        def calculate(paths):
            table, metadata = pipeline.engine_polars.calculate(paths)
            return table, {**metadata, "rows_used": metadata["rows_used"] + 1}

    monkeypatch.setitem(pipeline.ENGINES, "polars", WrongMetadata)
    result = compare.compare(repeats=1)
    assert not result.identical
    assert "polars metadata differs from pandas" in result.differences


def test_repeats_must_be_at_least_one(staged_raw):
    with pytest.raises(ValueError, match="at least 1"):
        compare.compare(repeats=0)


def test_missing_staged_files_are_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run the download first"):
        compare.compare(raw_dir=tmp_path / "nothing", repeats=1)


def test_the_report_is_readable(staged_raw):
    report = compare.format_report(compare.compare(repeats=2))
    assert "Results identical across engines: yes" in report
    assert "Rows used: 5 | days: 4 | total revenue: 18.50" in report
    for name, style in (("pandas", "ETL"), ("polars", "ETL"), ("duckdb", "ELT")):
        assert name in report and style in report
    assert "1 warm-up run, then 2 timed runs" in report
