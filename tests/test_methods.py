import ntpath
import os
import posixpath
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

from qbt_migrate.methods import backup_folder, convert_slashes, discover_bt_backup_path


def test_backup_folder():
    temp_dir = Path(tempfile.mkdtemp())  # Get a tmp dir
    fastresume_file_count = 20  # Number of test fastresume files to build
    torrent_file_count = 20  # Number of test torrent files to build
    invalid_file_count = 20  # Number of invalid files to build

    # Build test files
    for x in range(fastresume_file_count):
        with open(temp_dir / f"test_{x}.fastresume", "w") as f:
            f.write(f"This is file {x}")

    for x in range(torrent_file_count):
        with open(temp_dir / f"test_{x}.torrent", "w") as f:
            f.write(f"This is file {x}")

    for x in range(invalid_file_count):
        with open(temp_dir / f"test_{x}.invalid", "w") as f:
            f.write(f"This is invalid file {x}")

    # 'test.zip' will fail the filename check in archive if it gets archived
    archive_path = temp_dir / "test.zip"
    backup_folder(temp_dir, archive_path)  # Call backup_folder with torrent files included

    # Validate zip file
    with zipfile.ZipFile(archive_path, "r") as archive:
        assert archive.testzip() is None  # Check no errors
        # Assert that it has the correct file count
        assert len(archive.infolist()) == fastresume_file_count + torrent_file_count
        for file in archive.infolist():
            # Get the integer of the file
            filename = re.findall(r"test_(\d+).(?:fastresume)?(?:torrent)?", file.filename)
            assert len(filename) != 0  # Ensure we got the integer
            filename = filename[0]
            assert archive.read(file.filename) == bytes(f"This is file {filename}", "utf-8")  # Integrity Check

    archive_path = temp_dir / "test2.zip"
    backup_folder(temp_dir, archive_path, False)

    # Validate zip file
    with zipfile.ZipFile(archive_path, "r") as archive:
        assert archive.testzip() is None  # Check no errors
        # Assert that it has the correct file count
        assert len(archive.infolist()) == fastresume_file_count
        for file in archive.infolist():
            # Get the integer of the file
            filename = re.findall(r"test_(\d+).fastresume", file.filename)
            assert len(filename) != 0  # Ensure we got the integer
            filename = filename[0]
            assert archive.read(file.filename) == bytes(f"This is file {filename}", "utf-8")  # Integrity Check


@pytest.mark.parametrize(
    "path, target_os, expected_path",
    [
        ("C:/some/path", "windows", "C:\\some\\path"),
        ("C:\\some\\path", "windows", "C:\\some\\path"),
        ("\\some\\path\\for\\linux", "linux", "/some/path/for/linux"),
        ("/some/path/for/linux", "linux", "/some/path/for/linux"),
        ("\\some\\path\\for\\mac", "mac", "/some/path/for/mac"),
        ("/some/path/for/mac", "mac", "/some/path/for/mac"),
        (None, "invalid_os", None),
    ],
)
def test_convert_slashes(path: str, target_os: str, expected_path: str):
    if target_os == "invalid_os":
        with pytest.raises(ValueError):
            convert_slashes(path, target_os)
    else:
        assert convert_slashes(path, target_os) == expected_path


@pytest.mark.parametrize(
    "system, expected_path, envvar_overrides",
    [
        (
            ("win32", ntpath),
            "C:\\Users\\test\\AppData\\Local\\qBittorrent\\BT_backup",
            {"localappdata": "C:\\Users\\test\\AppData\\Local"},
        ),
        (("linux", posixpath), "/home/test/.local/share/data/qBittorrent/BT_backup", {"HOME": "/home/test"}),
        (("docker", posixpath), "/config/qBittorrent/BT_backup", {}),
    ],
)
def test_discover_bt_backup_path(monkeypatch, system: tuple, expected_path: str, envvar_overrides: dict):
    for env, val in envvar_overrides.items():
        monkeypatch.setenv(env, val)
    system, os_path_lib = system
    monkeypatch.setattr(os, "path", os_path_lib)
    if system == "docker":
        system = "linux"

        def mock_docker_env(_):
            return True

        monkeypatch.setattr(os.path, "isfile", mock_docker_env)
        monkeypatch.setattr(os.path, "isdir", mock_docker_env)

    monkeypatch.setattr(sys, "platform", system)
    assert discover_bt_backup_path() == expected_path
