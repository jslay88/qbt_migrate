"""Recovering the torrent name instead of showing an info hash.

A `.fastresume` is named after the 40 character info hash. The name lives in a
fallback chain, per qBittorrent's `BencodeResumeDataStorage::Worker::store` and
libtorrent's `write_resume_data`.
"""

import pytest

from qbt_migrate.classes import FastResume
from qbt_migrate.cli import main
from qbt_migrate.names import (
    name_from_data,
    name_from_info,
    name_from_torrent_file,
    torrent_name,
)


def info(name: str) -> dict:
    return {"name": name, "piece length": 262144}


@pytest.fixture
def torrent_pair(write_fastresume, temp_dir):
    """Write a `.fastresume` and optionally its sibling `.torrent`."""

    def _write(stem: str, resume: dict, metadata: dict | None = None):
        path = write_fastresume(f"{stem}.fastresume", resume)
        if metadata is not None:
            import bencodepy

            bencodepy.Bencode(encoding="utf-8", encoding_fallback="all").write(
                metadata, temp_dir / f"{stem}.torrent"
            )
        return path

    return _write


def test_normal_torrent_takes_the_name_from_the_torrent_file(torrent_pair):
    """The usual case: qBittorrent moved the info dict to <hash>.torrent."""
    path = torrent_pair(
        "aaaa",
        {"save_path": "S:\\Pictures", "qBt-name": "", "name": ""},
        {"info": info("Ubuntu 24.04 LTS Desktop amd64")},
    )
    assert FastResume(path).name == "Ubuntu 24.04 LTS Desktop amd64"


def test_a_rename_in_qbittorrent_wins(torrent_pair):
    path = torrent_pair(
        "bbbb",
        {
            "save_path": "S:\\Music",
            "qBt-name": "My Renamed Album",
            "name": "original.name.here",
        },
        {"info": info("original.name.here")},
    )
    assert FastResume(path).name == "My Renamed Album"


def test_libtorrent_name_is_used_when_there_is_no_torrent_file(torrent_pair):
    """A magnet with no metadata yet has no .torrent at all."""
    path = torrent_pair(
        "cccc",
        {"save_path": "S:\\Movies", "qBt-name": "", "name": "Some.Magnet"},
    )
    assert FastResume(path).name == "Some.Magnet"


def test_falls_back_to_the_hash(torrent_pair):
    path = torrent_pair("dddd", {"save_path": "S:\\Books"})
    assert FastResume(path).name == "dddd"


def test_an_embedded_info_dict_is_used(torrent_pair):
    """Some resume data still carries info inline."""
    path = torrent_pair(
        "eeee",
        {"save_path": "S:\\Shows", "info": info("Inline Name")},
    )
    assert FastResume(path).name == "Inline Name"


def test_a_corrupt_torrent_file_only_costs_the_label(
    write_fastresume, temp_dir
):
    """Refusing to migrate over unreadable metadata would be absurd."""
    path = write_fastresume("ffff.fastresume", {"save_path": "S:\\Pictures"})
    (temp_dir / "ffff.torrent").write_bytes(b"not bencode at all")

    assert FastResume(path).name == "ffff"


def test_blank_and_whitespace_names_are_ignored(torrent_pair):
    path = torrent_pair(
        "gggg",
        {"save_path": "S:\\X", "qBt-name": "   ", "name": "  Real Name  "},
    )
    assert FastResume(path).name == "Real Name"


@pytest.mark.parametrize(
    "data, expected",
    [
        ({}, ""),
        ({"info": "not-a-dict"}, ""),
        ({"info": {}}, ""),
        ({"info": {"name": 42}}, ""),
        ({"info": {"name": " Spaced "}}, "Spaced"),
    ],
)
def test_name_from_info_handles_schemaless_data(data, expected):
    # Bencode has no schema, so a wrong type is a real possibility.
    assert name_from_info(data) == expected


@pytest.mark.parametrize(
    "data, expected",
    [
        ({"qBt-name": "A", "name": "B"}, "A"),
        ({"qBt-name": "", "name": "B"}, "B"),
        ({"name": 5}, ""),
        ({}, ""),
    ],
)
def test_name_from_data_precedence(data, expected):
    assert name_from_data(data) == expected


def test_name_from_missing_torrent_file(temp_dir):
    assert name_from_torrent_file(temp_dir / "nope.torrent") == ""


def test_torrent_name_never_returns_empty(temp_dir):
    # Callers use this directly as a label, so it must always produce a value.
    assert torrent_name(temp_dir / "abc123.fastresume", {}) == "abc123"


def test_dry_run_shows_the_name(torrent_pair, temp_dir, cli_args, caplog):
    torrent_pair(
        "a" * 40,
        {"save_path": "S:\\Pictures", "qBt-savePath": "S:\\Pictures"},
        {"info": info("Ubuntu 24.04 LTS Desktop amd64")},
    )
    cli_args("-b", str(temp_dir), "-e", "S:\\", "-n", "/mnt/s/", "-d")

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        main()

    assert "Ubuntu 24.04 LTS Desktop amd64" in caplog.text
    assert "a" * 40 not in caplog.text


def test_failure_messages_name_the_torrent(
    torrent_pair, temp_dir, cli_args, caplog, monkeypatch
):
    """ "Failed to update <40 hex chars>" tells the user nothing."""
    torrent_pair(
        "b" * 40,
        {"save_path": "S:\\Pictures", "qBt-savePath": "S:\\Pictures"},
        {"info": info("Blender Open Movie")},
    )

    def boom(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(FastResume, "replace_paths", boom)
    cli_args("-b", str(temp_dir), "-e", "S:\\", "-n", "/mnt/s/", "-z")

    with caplog.at_level("ERROR", logger="qbt_migrate.classes"):
        assert main() == 1

    assert "Blender Open Movie" in caplog.text
