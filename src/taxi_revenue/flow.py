"""The same pipeline as a Prefect flow (the optional extension).

A flow is a Python function that Prefect watches: every step is a task, and Prefect
records each task's state, timing and logs. The calculation code is not repeated here.
The tasks only call the functions that the normal run already uses.
"""

from prefect import flow, task

from taxi_revenue import download, pipeline


@task(name="download", retries=2, retry_delay_seconds=5)
def download_task() -> list[tuple[str, bool]]:
    """Download the three monthly files. Existing valid files are kept."""
    results = download.download_all()
    return [(result.month, result.downloaded) for result in results]


@task(name="calculate")
def calculate_task(engine: str):
    """Run one engine on the staged files and return the table and the metadata."""
    return pipeline.calculate(engine, pipeline.raw_paths())


@task(name="write")
def write_task(table, metadata):
    """Write the CSV, the parquet file and the metadata file."""
    return pipeline.write_outputs(table, metadata)


@flow(name="daily-revenue", log_prints=True)
def daily_revenue_flow(engine: str = pipeline.DEFAULT_ENGINE) -> dict[str, object]:
    """Download, calculate with one engine, write the outputs."""
    if engine not in pipeline.ENGINES:  # fail at once, before any task starts
        raise ValueError(f"Unknown engine '{engine}'. Choose one of: {sorted(pipeline.ENGINES)}")
    download_task()
    table, metadata = calculate_task(engine)
    outputs = write_task(table, metadata)
    print(f"Engine {engine}: {metadata['rows_used']:,} trips, {metadata['days_in_output']} days")
    print(f"Written to {outputs.csv.parent}")
    return metadata
