"""Tests for the settings and the two small helper functions."""

from taxi_revenue import config


def test_file_name():
    assert config.file_name("2025-02") == "green_tripdata_2025-02.parquet"


def test_file_url_is_the_base_url_plus_the_file_name():
    assert config.file_url("2025-03") == f"{config.BASE_URL}/green_tripdata_2025-03.parquet"


def test_the_three_months_are_inside_the_date_window():
    assert config.WINDOW_START < config.WINDOW_END
    for month in config.MONTHS:
        assert config.WINDOW_START[:7] <= month < config.WINDOW_END[:7]


def test_data_folders_are_inside_the_project():
    assert config.RAW_DIR.parent == config.PROCESSED_DIR.parent
    assert config.RAW_DIR.parent.parent == config.PROJECT_ROOT
