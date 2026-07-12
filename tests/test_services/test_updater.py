"""Unit tests for the pure/deterministic parts of the updater service:
version parsing/compare and the GitHub Releases response -> ReleaseInfo
mapping. No network access -- urllib.request.urlopen is monkeypatched."""

from __future__ import annotations

import io
import json
import urllib.error

from gcm.services import updater


def _fake_urlopen(payload: dict):
    body = json.dumps(payload).encode("utf-8")

    class _CM:
        def __enter__(self):
            return io.BytesIO(body)

        def __exit__(self, *exc_info):
            return False

    def _urlopen(*args, **kwargs):
        return _CM()

    return _urlopen


def test_parse_version_with_leading_v():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_without_leading_v():
    assert updater.parse_version("0.5.0") == (0, 5, 0)


def test_parse_version_orders_correctly():
    assert updater.parse_version("0.5.0") < updater.parse_version("0.5.1")
    assert updater.parse_version("0.5.0") < updater.parse_version("0.10.0")


def test_no_update_when_already_current(monkeypatch):
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        _fake_urlopen({"tag_name": "v0.5.0", "body": "", "assets": []}))
    assert updater.check_latest_release("0.5.0") is None


def test_no_update_when_remote_is_older(monkeypatch):
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        _fake_urlopen({"tag_name": "v0.4.0", "body": "", "assets": []}))
    assert updater.check_latest_release("0.5.0") is None


def test_update_available_with_matching_asset(monkeypatch):
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        _fake_urlopen({
            "tag_name": "v0.6.0",
            "body": "New stuff",
            "assets": [
                {"name": "GraphicalCloudManager-macos.zip",
                 "browser_download_url": "https://example.com/macos.zip"},
                {"name": "GraphicalCloudManager-windows.zip",
                 "browser_download_url": "https://example.com/windows.zip"},
            ],
        }))
    monkeypatch.setattr(updater.sys, "platform", "darwin")

    release = updater.check_latest_release("0.5.0")

    assert release is not None
    assert release.version == "0.6.0"
    assert release.version_tuple == (0, 6, 0)
    assert release.notes == "New stuff"
    assert release.asset_url == "https://example.com/macos.zip"


def test_update_available_without_matching_asset(monkeypatch):
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        _fake_urlopen({
            "tag_name": "v0.6.0",
            "body": "",
            "assets": [{"name": "GraphicalCloudManager-windows.zip",
                        "browser_download_url": "https://example.com/windows.zip"}],
        }))
    monkeypatch.setattr(updater.sys, "platform", "darwin")

    release = updater.check_latest_release("0.5.0")

    assert release is not None
    assert release.asset_url is None


def test_no_releases_yet(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen({}))
    assert updater.check_latest_release("0.5.0") is None


def test_network_error_returns_none(monkeypatch):
    def _raise(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(updater.urllib.request, "urlopen", _raise)
    assert updater.check_latest_release("0.5.0") is None
