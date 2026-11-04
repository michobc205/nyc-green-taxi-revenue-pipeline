"""Tests for the pipeline: it calls an engine and writes the three output files."""

import json

import pandas as pd
import pytest

from conftest import STAGED_CSV
from taxi_revenue import config, download, pipeline


@pytest.fixture(params=sorted(pipeline.ENGINES))
def engine_name(request):
    return request.param


def test_the_csv_has_the_exact_expected_content(engine_name, staged_raw, tmp_path):
    out = tmp_path / "out"
    outputs, _ = pipeline.run_pipeline(engine_name, output_dir=out, download_first=False)
    raw_bytes = outputs.csv.read_bytes()
    assert raw_bytes.decode("utf-8") == STAGED_CSV
    assert b"\r" not in raw_bytes  # always LF, also on Windows


def test_all_three_files_are_written(engine_name, staged_raw, tmp_path):
    out = tmp_path / "out"
    outputs, _ = pipeline.run_pipeline(engine_name, output_dir=out, download_first=False)
    assert sorted(path.name for path in out.iterdir()) == [
        "daily_revenue.csv",
        "daily_revenue.parquet",
        "pipeline_metadata.json",
    ]
    assert outputs.csv.parent == out


def test_the_parquet_file_holds_the_same_table_as_the_csv(engine_name, staged_raw, tmp_path):
    outputs, _ = pipeline.run_pipeline(
        engine_name, output_dir=tmp_path / "out", download_first=False
    )
    from_csv = pd.read_csv(outputs.csv)
    from_parquet = pd.read_parquet(outputs.parquet)
    assert from_parquet["service_date"].tolist() == from_csv["service_date"].tolist()
    assert from_parquet["trip_count"].tolist() == from_csv["trip_count"].tolist()
    assert from_parquet["daily_revenue"].tolist() == from_csv["daily_revenue"].tolist()


def test_the_metadata_file(engine_name, staged_raw, tmp_path):
    outputs, meta = pipeline.run_pipeline(
        engine_name, output_dir=tmp_path / "out", download_first=False
    )
    text = outputs.metadata_json.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    saved = json.loads(text)
    assert saved == meta
    assert saved["engine"] == engine_name
    assert saved["rows_read"] == 6
    assert saved["rows_used"] == 5
    assert saved["rows_dropped_outside_window"] == 1
    assert saved["negative_amount_trips"] == 1
    assert saved["revenue_total"] == 18.5
    assert saved["source_files"] == [config.file_name(m) for m in config.MONTHS]
    assert saved["date_window"] == [config.WINDOW_START, config.WINDOW_END]


def test_all_engines_write_identical_csv_files(staged_raw, tmp_path):
    contents = {
        name: pipeline.run_pipeline(name, output_dir=tmp_path / name, download_first=False)[0]
        .csv.read_bytes()
        for name in pipeline.ENGINES
    }
    assert len(set(contents.values())) == 1


def test_the_default_output_folder_is_the_processed_folder(staged_raw):
    outputs, _ = pipeline.run_pipeline(download_first=False)
    assert outputs.csv.parent == config.PROCESSED_DIR
    assert outputs.csv.exists()


def test_the_output_folder_is_created_when_missing(staged_raw, tmp_path):
    out = tmp_path / "a" / "b" / "c"
    outputs, _ = pipeline.run_pipeline("pandas", output_dir=out, download_first=False)
    assert outputs.csv.exists()


def test_an_unknown_engine_is_an_error(staged_raw):
    with pytest.raises(ValueError, match="Unknown engine 'excel'"):
        pipeline.run_pipeline("excel", download_first=False)


def test_missing_staged_files_are_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run the download first"):
        pipeline.run_pipeline("pandas", raw_dir=tmp_path / "empty", download_first=False)


def test_the_download_runs_first_unless_switched_off(staged_raw, monkeypatch):
    calls = []
    monkeypatch.setattr(download, "download_all", lambda **kwargs: calls.append(kwargs))
    pipeline.run_pipeline("pandas")
    assert calls == [{"raw_dir": None}]
    calls.clear()
    pipeline.run_pipeline("pandas", download_first=False)
    assert calls == []
