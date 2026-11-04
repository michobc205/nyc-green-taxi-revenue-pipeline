"""Command line: download the data, run one engine, or compare all three.

    taxi-revenue download [--force]
    taxi-revenue run [--engine pandas|polars|duckdb] [--no-download]
    taxi-revenue compare [--repeats 5]
"""

import click
import requests

from taxi_revenue import compare as compare_module
from taxi_revenue import config, pipeline
from taxi_revenue import download as download_module

# Problems we expect and explain in plain words, instead of a long traceback.
EXPECTED_ERRORS = (FileNotFoundError, ValueError, requests.RequestException)


def _short(path):
    """Show a path relative to the project folder when possible."""
    try:
        return path.relative_to(config.PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


@click.group()
def main():
    """Daily revenue pipeline for the NYC Green Taxi trip data (Jan to Mar 2025)."""


@main.command()
@click.option("--force", is_flag=True, help="Download again, even if the files exist.")
def download(force):
    """Download the three monthly files into data/raw."""
    try:
        results = download_module.download_all(force=force)
    except EXPECTED_ERRORS as error:
        raise click.ClickException(str(error)) from error
    for result in results:
        state = "downloaded" if result.downloaded else "already there"
        click.echo(f"{result.month}: {state} ({result.size_bytes:,} bytes)")


@main.command()
@click.option(
    "--engine",
    type=click.Choice(sorted(pipeline.ENGINES)),
    default=pipeline.DEFAULT_ENGINE,
    show_default=True,
    help="Which engine does the calculation.",
)
@click.option("--no-download", is_flag=True, help="Do not download. Use the files in data/raw.")
def run(engine, no_download):
    """Calculate the daily revenue and write the files to data/processed."""
    try:
        outputs, meta = pipeline.run_pipeline(engine, download_first=not no_download)
    except EXPECTED_ERRORS as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Engine: {engine}")
    click.echo(
        f"Rows read: {meta['rows_read']:,} | used: {meta['rows_used']:,} | "
        f"dropped outside the date window: {meta['rows_dropped_outside_window']:,} | "
        f"dropped for missing values: {meta['rows_dropped_missing_values']:,}"
    )
    click.echo(
        f"Kept negative amounts: {meta['negative_amount_trips']:,} "
        f"(sum {meta['negative_amount_sum']:,.2f}) | "
        f"kept zero amounts: {meta['zero_amount_trips']:,}"
    )
    click.echo(f"Days: {meta['days_in_output']} | total revenue: {meta['revenue_total']:,.2f}")
    for path in (outputs.csv, outputs.parquet, outputs.metadata_json):
        click.echo(f"Written: {_short(path)}")


@main.command()
@click.option(
    "--repeats",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="How many timed runs per engine.",
)
def compare(repeats):
    """Run all three engines, check the results are identical and time them."""
    try:
        result = compare_module.compare(repeats=repeats)
    except EXPECTED_ERRORS as error:
        raise click.ClickException(str(error)) from error
    click.echo(compare_module.format_report(result))


@main.command()
@click.option(
    "--engine",
    type=click.Choice(sorted(pipeline.ENGINES)),
    default=pipeline.DEFAULT_ENGINE,
    show_default=True,
    help="Which engine does the calculation.",
)
def flow(engine):
    """Run the same pipeline as a Prefect flow (optional extension)."""
    # Imported here, because Prefect is slow to load and the other commands do not need it.
    from taxi_revenue.flow import daily_revenue_flow

    try:
        metadata = daily_revenue_flow(engine)
    except EXPECTED_ERRORS as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Flow finished. Total revenue: {metadata['revenue_total']:,.2f}")
