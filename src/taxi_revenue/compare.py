"""Compare the three engines: same result? how fast?

Each engine gets one warm-up run (not timed), so the first read of the files from
disk does not punish whoever happens to go first. Then every engine is timed
several times. The timing covers the whole calculation: reading the files,
applying the rules and building the result table. Writing files is not included.
"""

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from taxi_revenue import pipeline

# Which style each engine follows (see the README for the difference).
STYLES = {"pandas": "ETL", "polars": "ETL", "duckdb": "ELT"}


@dataclass(frozen=True)
class EngineTiming:
    """All timed runs of one engine, in seconds."""

    engine: str
    seconds: list[float]

    @property
    def median(self) -> float:
        return statistics.median(self.seconds)

    @property
    def fastest(self) -> float:
        return min(self.seconds)

    @property
    def slowest(self) -> float:
        return max(self.seconds)


@dataclass(frozen=True)
class ComparisonResult:
    """The outcome of one comparison."""

    timings: list[EngineTiming]
    identical: bool
    differences: list[str]
    rows_used: int
    days: int
    revenue_total: float
    repeats: int


def _without_engine(metadata: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in metadata.items() if key != "engine"}


def compare(raw_dir: Path | None = None, repeats: int = 5) -> ComparisonResult:
    """Run every engine, check the results are identical and time them."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1.")
    paths = pipeline.raw_paths(raw_dir)
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing staged file(s): {missing}. Run the download first.")

    timings = []
    results = {}
    for name, engine in pipeline.ENGINES.items():
        results[name] = engine.calculate(paths)  # warm-up run, not timed
        seconds = []
        for _ in range(repeats):
            started = time.perf_counter()
            engine.calculate(paths)
            seconds.append(time.perf_counter() - started)
        timings.append(EngineTiming(name, seconds))

    base_name = pipeline.DEFAULT_ENGINE
    base_table, base_meta = results[base_name]
    differences = []
    for name, (table, meta) in results.items():
        if name == base_name:
            continue
        try:
            pd.testing.assert_frame_equal(base_table, table, check_exact=True)
        except AssertionError as error:
            differences.append(f"{name} table differs from {base_name}: {str(error)[:200]}")
        if _without_engine(meta) != _without_engine(base_meta):
            differences.append(f"{name} metadata differs from {base_name}")

    return ComparisonResult(
        timings=timings,
        identical=not differences,
        differences=differences,
        rows_used=int(base_meta["rows_used"]),
        days=int(base_meta["days_in_output"]),
        revenue_total=float(base_meta["revenue_total"]),
        repeats=repeats,
    )


def format_report(result: ComparisonResult) -> str:
    """Return the comparison as plain text."""
    lines = [
        f"Rows used: {result.rows_used:,} | days: {result.days} | "
        f"total revenue: {result.revenue_total:,.2f}",
        f"Results identical across engines: {'yes' if result.identical else 'NO'}",
        "",
        f"{'engine':<8}{'style':<7}{'median (s)':>12}{'fastest (s)':>13}{'slowest (s)':>13}",
    ]
    for timing in result.timings:
        lines.append(
            f"{timing.engine:<8}{STYLES.get(timing.engine, '?'):<7}"
            f"{timing.median:>12.3f}{timing.fastest:>13.3f}{timing.slowest:>13.3f}"
        )
    lines.append(f"(each engine: 1 warm-up run, then {result.repeats} timed runs)")
    lines.extend(result.differences)
    return "\n".join(lines)
