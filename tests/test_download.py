"""Tests for the download code. A tiny web server runs on this computer during the
tests, so nothing touches the real internet."""

import functools
import http.server
import threading

import pandas as pd
import pytest
import requests

from taxi_revenue import config, download


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output clean
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Serve good parquet files for the three months, a fake one for 2025-04, nothing else."""
    site = tmp_path / "site"
    site.mkdir()
    for month in config.MONTHS:
        pd.DataFrame({"a": range(100)}).to_parquet(site / config.file_name(month))
    (site / config.file_name("2025-04")).write_bytes(b"<html>This is not parquet</html>")

    handler = functools.partial(QuietHandler, directory=str(site))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "BASE_URL", f"http://127.0.0.1:{httpd.server_address[1]}")
    yield site
    httpd.shutdown()
    httpd.server_close()


def test_downloads_every_month_into_the_folder(server, tmp_path):
    raw = tmp_path / "raw"
    results = download.download_all(raw_dir=raw)
    assert [r.month for r in results] == list(config.MONTHS)
    assert all(r.downloaded for r in results)
    for month in config.MONTHS:
        assert (raw / config.file_name(month)).read_bytes() == (server / config.file_name(month)).read_bytes()


def test_the_folder_is_created_when_missing(server, tmp_path):
    raw = tmp_path / "deep" / "nested" / "raw"
    download.download_month("2025-01", raw)
    assert (raw / config.file_name("2025-01")).exists()


def test_an_existing_valid_file_is_kept(server, tmp_path):
    raw = tmp_path / "raw"
    download.download_all(raw_dir=raw)
    target = raw / config.file_name("2025-02")
    before = target.stat().st_mtime_ns
    second = download.download_all(raw_dir=raw)
    assert not any(r.downloaded for r in second)
    assert target.stat().st_mtime_ns == before


def test_force_downloads_again(server, tmp_path):
    raw = tmp_path / "raw"
    download.download_all(raw_dir=raw)
    again = download.download_all(raw_dir=raw, force=True)
    assert all(r.downloaded for r in again)


def test_a_broken_existing_file_is_refused(server, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / config.file_name("2025-01")).write_bytes(b"junk junk junk")
    with pytest.raises(ValueError, match="not a valid parquet file"):
        download.download_month("2025-01", raw)


def test_a_download_that_is_not_parquet_is_refused_and_leaves_nothing(server, tmp_path):
    raw = tmp_path / "raw"
    with pytest.raises(ValueError, match="not a valid parquet file"):
        download.download_month("2025-04", raw)
    assert list(raw.iterdir()) == []  # no finished file and no .part file


def test_a_file_missing_on_the_server_is_an_error_and_leaves_nothing(server, tmp_path):
    raw = tmp_path / "raw"
    with pytest.raises(requests.HTTPError):
        download.download_month("2025-09", raw)
    assert list(raw.iterdir()) == []


def test_looks_like_parquet(tmp_path):
    good = tmp_path / "good.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(good)
    too_short = tmp_path / "short.parquet"
    too_short.write_bytes(b"PAR1")
    wrong_end = tmp_path / "wrong_end.parquet"
    wrong_end.write_bytes(b"PAR1 and then something else")
    assert download.looks_like_parquet(good)
    assert not download.looks_like_parquet(too_short)
    assert not download.looks_like_parquet(wrong_end)
