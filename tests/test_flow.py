"""Tests for the Prefect flow.

The tasks are tested directly (task.fn runs the plain function, no server needed).
The whole flow is tested once inside Prefect's own test harness, which starts a
temporary server and throws it away afterwards, so your Prefect settings and your
Prefect database are never touched.
"""

import pytest
from prefect.testing.utilities import prefect_test_harness

from taxi_revenue import config, download, pipeline
from taxi_revenue.flow import calculate_task, daily_revenue_flow, download_task, write_task


@pytest.fixture(scope="module")
def prefect_server():
    patch = pytest.MonkeyPatch()
    patch.setenv("PREFECT_SERVER_ANALYTICS_ENABLED", "false")  # send nothing, even in tests
    try:
        with prefect_test_harness():
            yield
    finally:
        patch.undo()


def test_download_task_calls_the_download_code(monkeypatch):
    results = [download.DownloadResult(m, config.RAW_DIR / m, i == 0, 10) for i, m in enumerate(config.MONTHS)]
    monkeypatch.setattr(download, "download_all", lambda: results)
    assert download_task.fn() == [("2025-01", True), ("2025-02", False), ("2025-03", False)]


def test_calculate_task_gives_the_same_result_as_the_pipeline(staged_raw):
    table, metadata = calculate_task.fn("polars")
    expected_table, expected_metadata = pipeline.calculate("polars", pipeline.raw_paths())
    assert table.equals(expected_table)
    assert metadata == expected_metadata


def test_write_task_writes_the_three_files(staged_raw):
    table, metadata = calculate_task.fn("pandas")
    outputs = write_task.fn(table, metadata)
    assert outputs.csv.exists() and outputs.parquet.exists() and outputs.metadata_json.exists()


def test_the_whole_flow(prefect_server, staged_raw, monkeypatch):
    monkeypatch.setattr(download, "download_all", lambda: [])  # the files are already staged
    metadata = daily_revenue_flow("duckdb")
    assert metadata["engine"] == "duckdb"
    assert metadata["rows_used"] == 5
    assert (config.PROCESSED_DIR / "daily_revenue.csv").exists()


def test_the_flow_refuses_an_unknown_engine(prefect_server, staged_raw):
    with pytest.raises(ValueError, match="Unknown engine 'excel'"):
        daily_revenue_flow("excel")
