"""BT_backup auto-detection, per qBittorrent's own resolution order.

Closes #71. The old implementation returned a single hardcoded path per
platform: `%LOCALAPPDATA%\\qBittorrent\\BT_backup` on Windows (correct) and
`$HOME/.local/share/data/qBittorrent/BT_backup` everywhere else. That path is
the pre-4.x Linux layout, and it was also handed to macOS, where it is never
right.

Reference: `Private::DefaultProfile::dataLocation` in
https://github.com/qbittorrent/qBittorrent/blob/master/src/base/profile_p.cpp
"""

import sys
from pathlib import Path

import pytest

from qbt_migrate.methods import (
    bt_backup_path_candidates,
    discover_bt_backup_path,
)


DOCKER_PATH = Path("/config/qBittorrent/BT_backup")


@pytest.fixture
def fake_home(monkeypatch, temp_dir):
    monkeypatch.setenv("HOME", str(temp_dir))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    # Nothing is a container unless a test says so. `/.dockerenv` is the only
    # `is_file` call in this code path.
    monkeypatch.setattr("qbt_migrate.methods.Path.is_file", lambda self: False)
    return temp_dir


@pytest.fixture
def platform(monkeypatch):
    def _set(name: str) -> None:
        monkeypatch.setattr(sys, "platform", name)

    return _set


@pytest.fixture
def in_container(monkeypatch):
    monkeypatch.setattr("qbt_migrate.methods.Path.is_file", lambda self: True)


def test_windows_uses_local_app_data(monkeypatch, platform):
    platform("win32")
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\test\\AppData\\Local")
    assert bt_backup_path_candidates() == [
        Path("C:\\Users\\test\\AppData\\Local") / "qBittorrent" / "BT_backup"
    ]


def test_macos_uses_application_support(fake_home, platform):
    platform("darwin")
    assert bt_backup_path_candidates() == [
        fake_home
        / "Library"
        / "Application Support"
        / "qBittorrent"
        / "BT_backup"
    ]


def test_linux_prefers_current_layout_over_legacy(fake_home, platform):
    platform("linux")
    assert bt_backup_path_candidates() == [
        fake_home / ".local" / "share" / "qBittorrent" / "BT_backup",
        fake_home / ".local" / "share" / "data" / "qBittorrent" / "BT_backup",
    ]


def test_linux_honours_xdg_data_home(monkeypatch, fake_home, platform):
    platform("linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_home / "xdg"))
    assert bt_backup_path_candidates()[0] == (
        fake_home / "xdg" / "qBittorrent" / "BT_backup"
    )


def test_container_config_is_checked_first(fake_home, platform, in_container):
    platform("linux")
    assert bt_backup_path_candidates()[0] == DOCKER_PATH


def test_container_path_is_absent_outside_a_container(fake_home, platform):
    platform("linux")
    assert DOCKER_PATH not in bt_backup_path_candidates()


def test_returns_current_layout_when_it_exists(fake_home, platform):
    platform("linux")
    current = fake_home / ".local/share/qBittorrent/BT_backup"
    legacy = fake_home / ".local/share/data/qBittorrent/BT_backup"
    current.mkdir(parents=True)
    legacy.mkdir(parents=True)
    assert discover_bt_backup_path() == current


def test_falls_back_to_legacy_when_only_it_exists(fake_home, platform):
    """qBittorrent keeps using the legacy dir when it is the only one there."""
    platform("linux")
    legacy = fake_home / ".local/share/data/qBittorrent/BT_backup"
    legacy.mkdir(parents=True)
    assert discover_bt_backup_path() == legacy


def test_returns_preferred_candidate_when_nothing_exists(fake_home, platform):
    platform("linux")
    assert discover_bt_backup_path() == (
        fake_home / ".local/share/qBittorrent/BT_backup"
    )


def test_logs_every_candidate_when_nothing_is_found(
    fake_home, platform, caplog
):
    platform("linux")
    with caplog.at_level("DEBUG", logger="qbt_migrate.methods"):
        discover_bt_backup_path()
    assert "No BT_backup directory found" in caplog.text
    assert ".local/share/data/qBittorrent/BT_backup" in caplog.text
