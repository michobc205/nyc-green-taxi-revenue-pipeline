"""Tests for the command line (download, run, compare)."""

import pytest
from click.testing import CliRunner

from taxi_revenue import config, download
from taxi_revenue.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_help_lists_the_three_commands(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in ("download", "run", "compare"):
        assert command in result.output


def test_run_prints_a_summary_and_writes_the_files(runner, staged_raw):
    result = runner.invoke(main, ["run", "--no-download"])
    assert result.exit_code == 0, result.output
    assert "Engine: pandas" in result.output
    assert "Rows read: 6 | used: 5" in result.output
    assert "dropped outside the date window: 1" in result.output
    assert "Kept negative amounts: 1 (sum -2.50)" in result.output
    assert "Days: 4 | total revenue: 18.50" in result.output
    assert "Written: data/processed/daily_revenue.csv" in result.output
    assert (config.PROCESSED_DIR / "daily_revenue.csv").exists()


def test_run_with_another_engine(runner, staged_raw):
    result = runner.invoke(main, ["run", "--engine", "duckdb", "--no-download"])
    assert result.exit_code == 0, result.output
    assert "Engine: duckdb" in result.output


def test_an_unknown_engine_is_refused(runner, staged_raw):
    result = runner.invoke(main, ["run", "--engine", "excel"])
    assert result.exit_code == 2
    assert "is not one of" in result.output


def test_missing_files_give_a_short_message_not_a_traceback(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "nothing")
    result = runner.invoke(main, ["run", "--no-download"])
    assert result.exit_code == 1
    assert "Run the download first" in result.output
    assert "Traceback" not in result.output


def test_compare_reports_identical_results(runner, staged_raw):
    result = runner.invoke(main, ["compare", "--repeats", "1"])
    assert result.exit_code == 0, result.output
    assert "Results identical across engines: yes" in result.output
    for name in ("pandas", "polars", "duckdb"):
        assert name in result.output


def test_compare_needs_at_least_one_repeat(runner, staged_raw):
    result = runner.invoke(main, ["compare", "--repeats", "0"])
    assert result.exit_code == 2


def test_download_prints_one_line_per_month_and_passes_force(runner, monkeypatch, tmp_path):
    seen = []

    def fake_download_all(force=False):
        seen.append(force)
        return [
            download.DownloadResult(m, tmp_path / m, downloaded=(i == 0), size_bytes=1000 + i)
            for i, m in enumerate(config.MONTHS)
        ]

    monkeypatch.setattr(download, "download_all", fake_download_all)
    result = runner.invoke(main, ["download", "--force"])
    assert result.exit_code == 0
    assert "2025-01: downloaded (1,000 bytes)" in result.output
    assert "2025-02: already there (1,001 bytes)" in result.output
    assert seen == [True]


def test_flow_command_passes_the_engine_to_the_flow(runner, monkeypatch):
    import taxi_revenue.flow as flow_module

    seen = []

    def fake_flow(engine):
        seen.append(engine)
        return {"revenue_total": 1234.5}

    monkeypatch.setattr(flow_module, "daily_revenue_flow", fake_flow)
    result = runner.invoke(main, ["flow", "--engine", "polars"])
    assert result.exit_code == 0, result.output
    assert seen == ["polars"]
    assert "Flow finished. Total revenue: 1,234.50" in result.output


def test_flow_command_refuses_an_unknown_engine(runner):
    result = runner.invoke(main, ["flow", "--engine", "excel"])
    assert result.exit_code == 2
