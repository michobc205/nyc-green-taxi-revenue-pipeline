"""Run the whole pipeline: download, calculate with one engine, write the outputs.

Three files are written to the output folder:
  daily_revenue.csv         the result table, easy to open anywhere
  daily_revenue.parquet     the same table in a typed, compact format
  pipeline_metadata.json    counts that explain what happened to the rows
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from taxi_revenue import (
    config,
    download,
    engine_duckdb,
    engine_pandas,
    engine_polars,
)

ENGINES = {
    engine_pandas.ENGINE_NAME: engine_pandas,
    engine_polars.ENGINE_NAME: engine_polars,
    engine_duckdb.ENGINE_NAME: engine_duckdb,
}
DEFAULT_ENGINE = "pandas"


@dataclass(frozen=True)
class PipelineOutputs:
    """The paths written by one run."""

    csv: Path
    parquet: Path
    metadata_json: Path


def raw_paths(raw_dir: Path | None = None) -> list[Path]:
    """Return the expected staged file of every month."""
    raw_dir = config.RAW_DIR if raw_dir is None else raw_dir
    return [raw_dir / config.file_name(month) for month in config.MONTHS]


def write_outputs(
    table: pd.DataFrame, metadata: dict[str, object], output_dir: Path | None = None
) -> PipelineOutputs:
    """Write the table and the metadata. Line endings are always LF."""
    output_dir = config.PROCESSED_DIR if output_dir is None else output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = PipelineOutputs(
        csv=output_dir / "daily_revenue.csv",
        parquet=output_dir / "daily_revenue.parquet",
        metadata_json=output_dir / "pipeline_metadata.json",
    )
    table.to_csv(outputs.csv, index=False, lineterminator="\n")
    table.to_parquet(outputs.parquet, index=False)
    outputs.metadata_json.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return outputs


def calculate(engine: str, paths: list[Path]) -> tuple[pd.DataFrame, dict[str, object]]:
    """Run one engine. The metadata also names the source files and the date window."""
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine '{engine}'. Choose one of: {sorted(ENGINES)}")
    table, metadata = ENGINES[engine].calculate(paths)
    metadata = {
        **metadata,
        "source_files": [path.name for path in paths],
        "date_window": [config.WINDOW_START, config.WINDOW_END],
    }
    return table, metadata


def run_pipeline(
    engine: str = DEFAULT_ENGINE,
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
    download_first: bool = True,
) -> tuple[PipelineOutputs, dict[str, object]]:
    """Run one engine end to end and return the written paths and the metadata."""
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine '{engine}'. Choose one of: {sorted(ENGINES)}")

    if download_first:
        download.download_all(raw_dir=raw_dir)
    paths = raw_paths(raw_dir)
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing staged file(s): {missing}. Run the download first.")

    table, metadata = calculate(engine, paths)
    outputs = write_outputs(table, metadata, output_dir)
    return outputs, metadata
