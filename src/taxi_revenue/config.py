"""Settings shared by every part of the pipeline.

Everything that may change (months, links, folders, rules) lives here,
so no other file needs to repeat it.
"""

from pathlib import Path

# The three months we process.
MONTHS = ("2025-01", "2025-02", "2025-03")

# Where the public parquet files live, and how each file is named.
BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
FILE_NAME_TEMPLATE = "green_tripdata_{month}.parquet"
DOWNLOAD_TIMEOUT_SECONDS = 120

# Rule 1: only trips picked up inside this window count.
# The start day is included, the end day is not.
WINDOW_START = "2025-01-01"
WINDOW_END = "2025-04-01"

# The two columns the calculation needs.
PICKUP_COLUMN = "lpep_pickup_datetime"
AMOUNT_COLUMN = "total_amount"

# Folders are found from this file, so commands work from any folder.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def file_name(month: str) -> str:
    """Return the file name of one month, for instance green_tripdata_2025-01.parquet."""
    return FILE_NAME_TEMPLATE.format(month=month)


def file_url(month: str) -> str:
    """Return the download link of one month."""
    return f"{BASE_URL}/{file_name(month)}"
