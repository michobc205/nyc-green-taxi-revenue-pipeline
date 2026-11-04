"""Download the monthly Green Taxi files into the staging folder (data/raw).

Staging means: the files are saved exactly as downloaded, unchanged.
The calculation reads them later, from disk, never from the internet.
"""

from dataclasses import dataclass
from pathlib import Path

import requests

from taxi_revenue import config

# Every real parquet file starts and ends with these 4 bytes.
PARQUET_MARKER = b"PAR1"


@dataclass(frozen=True)
class DownloadResult:
    """What happened for one month."""

    month: str
    path: Path
    downloaded: bool  # False means the file was already there and was kept
    size_bytes: int


def looks_like_parquet(path: Path) -> bool:
    """Return True if the file starts and ends with the parquet marker."""
    if path.stat().st_size < 2 * len(PARQUET_MARKER):
        return False
    with path.open("rb") as file:
        start = file.read(len(PARQUET_MARKER))
        file.seek(-len(PARQUET_MARKER), 2)
        end = file.read(len(PARQUET_MARKER))
    return start == PARQUET_MARKER and end == PARQUET_MARKER


def download_month(
    month: str, raw_dir: Path | None = None, force: bool = False
) -> DownloadResult:
    """Download one month. An existing, valid file is kept unless force is True."""
    raw_dir = config.RAW_DIR if raw_dir is None else raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / config.file_name(month)

    if target.exists() and not force:
        if not looks_like_parquet(target):
            raise ValueError(
                f"{target} exists but is not a valid parquet file. "
                "Delete it, or run again with force."
            )
        return DownloadResult(month, target, False, target.stat().st_size)

    # Write to a temporary name first, so a broken download never looks finished.
    part = target.with_name(target.name + ".part")
    try:
        url = config.file_url(month)
        with requests.get(
            url, stream=True, timeout=config.DOWNLOAD_TIMEOUT_SECONDS
        ) as response:
            response.raise_for_status()
            with part.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    output.write(chunk)
        if not looks_like_parquet(part):
            raise ValueError(f"The download from {url} is not a valid parquet file.")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)

    return DownloadResult(month, target, True, target.stat().st_size)


def download_all(
    months: tuple[str, ...] = config.MONTHS,
    raw_dir: Path | None = None,
    force: bool = False,
) -> list[DownloadResult]:
    """Download every month and return one result per month."""
    return [download_month(month, raw_dir, force) for month in months]
