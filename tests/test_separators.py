"""Separator handling across the two conventions qBittorrent writes.

Regression coverage for #75. A fastresume written on Windows stores backslashes
in `save_path` and the `qBt-*` keys; one written on Linux or Mac stores forward
slashes. The tool used to assume a convention per key, which meant a
replacement silently matched nothing whenever the file did not use it, leaving
the old drive letter in place for qBittorrent to act on.
"""

import pytest

from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.enums import TargetOS
from qbt_migrate.methods import matches_path, replace_path, separator_variants


WINDOWS_KEYS = {
    "save_path": "S:\\Pictures\\",
    "qBt-savePath": "S:\\Pictures\\",
    "qBt-downloadPath": "S:\\Pictures\\",
    "mapped_files": ["S:\\Pictures\\a.jpg", "S:\\Pictures\\b.jpg"],
}

POSIX_KEYS = {
    "save_path": "S:/Pictures/",
    "qBt-savePath": "S:/Pictures/",
    "qBt-downloadPath": "S:/Pictures/",
    "mapped_files": ["S:/Pictures/a.jpg", "S:/Pictures/b.jpg"],
}

MIXED_KEYS = {
    "save_path": "S:\\Pictures\\",
    "qBt-savePath": "S:/Pictures/",
    "qBt-downloadPath": "S:\\Pictures\\",
    "mapped_files": ["S:/Pictures/a.jpg", "S:\\Pictures\\b.jpg"],
}


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param(WINDOWS_KEYS, id="stored-windows"),
        pytest.param(POSIX_KEYS, id="stored-posix"),
        pytest.param(MIXED_KEYS, id="stored-mixed"),
    ],
)
@pytest.mark.parametrize(
    "existing_path",
    [
        pytest.param("S:\\", id="pattern-windows"),
        pytest.param("S:/", id="pattern-posix"),
    ],
)
def test_windows_to_posix_replaces_every_key(
    write_fastresume, stored, existing_path
):
    """`-e 'S:\\' -n /mnt/s/` and `-e S:/ -n /mnt/s/` are equivalent.

    Previously only the key that happened to match the assumed convention was
    rewritten, and the other was left with the drive letter, so qBittorrent
    tried to relocate the torrent to `$HOME/S:/Pictures`.
    """
    path = write_fastresume("win.fastresume", dict(stored))
    fast_resume = FastResume(path)
    fast_resume.replace_paths(
        existing_path,
        "/mnt/s/",
        target_os=TargetOS.POSIX,
        save_file=False,
        create_backup=False,
    )
    assert fast_resume.save_path == "/mnt/s/Pictures/"
    assert fast_resume.qbt_save_path == "/mnt/s/Pictures/"
    assert fast_resume.qbt_download_path == "/mnt/s/Pictures/"
    assert fast_resume.mapped_files == [
        "/mnt/s/Pictures/a.jpg",
        "/mnt/s/Pictures/b.jpg",
    ]


@pytest.mark.parametrize(
    "existing_path",
    [
        pytest.param("S:\\", id="pattern-windows"),
        pytest.param("S:/", id="pattern-posix"),
    ],
)
def test_replacement_is_idempotent(write_fastresume, existing_path):
    """A second identical run has to be a no-op.

    The reports on #75 and #65 describe needing several passes. Once one pass
    rewrites every key there is nothing left for a second pass to match.
    """
    path = write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    fast_resume = FastResume(path)
    replace = {
        "existing_path": existing_path,
        "new_path": "/mnt/s/",
        "target_os": TargetOS.POSIX,
        "save_file": False,
        "create_backup": False,
    }
    fast_resume.replace_paths(**replace)
    after_first_pass = dict(fast_resume._data)

    fast_resume.replace_paths(**replace)
    assert dict(fast_resume._data) == after_first_pass


def test_posix_to_windows_replaces_every_key(write_fastresume):
    path = write_fastresume(
        "nix.fastresume",
        {
            "save_path": "/torrents/movies",
            "qBt-savePath": "/torrents/movies",
            "mapped_files": ["/torrents/movies/a.mkv"],
        },
    )
    fast_resume = FastResume(path)
    fast_resume.replace_paths(
        "/torrents",
        "Z:\\Torrents",
        target_os=TargetOS.WINDOWS,
        save_file=False,
        create_backup=False,
    )
    assert fast_resume.save_path == "Z:\\Torrents\\movies"
    assert fast_resume.qbt_save_path == "Z:\\Torrents\\movies"
    assert fast_resume.mapped_files == ["Z:\\Torrents\\movies\\a.mkv"]


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param(WINDOWS_KEYS, id="stored-windows"),
        pytest.param(POSIX_KEYS, id="stored-posix"),
    ],
)
@pytest.mark.parametrize(
    "existing_path",
    [
        pytest.param("S:\\", id="pattern-windows"),
        pytest.param("S:/", id="pattern-posix"),
    ],
)
def test_discovery_is_separator_agnostic(
    write_fastresume, temp_dir, stored, existing_path
):
    """Discovery has to find the file whichever convention was used.

    Matching only the literal pattern meant relevant files were skipped
    entirely on the first pass, which is the other half of the multiple-passes
    reports.
    """
    write_fastresume("win.fastresume", dict(stored))
    discovered = list(
        QBTBatchMove.discover_relevant_fast_resume(
            temp_dir, existing_path, False, True
        )
    )
    assert len(discovered) == 1


def test_discovery_ignores_non_fastresume_files(write_fastresume, temp_dir):
    """BT_backup also holds .torrent files and our own backup archives."""
    write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    (temp_dir / "win.torrent").write_bytes(b"d4:infod4:name1:aee")
    (temp_dir / "fastresume_backup20260804000000.zip").write_bytes(
        b"PK\x05\x06"
    )
    (temp_dir / "win.fastresume.20260804000000.bkup").write_bytes(b"de")

    discovered = list(
        QBTBatchMove.discover_relevant_fast_resume(
            temp_dir, "S:\\", False, True
        )
    )
    assert [f.file_path.name for f in discovered] == ["win.fastresume"]


def test_discovery_still_skips_irrelevant_files(write_fastresume, temp_dir):
    write_fastresume("other.fastresume", dict(WINDOWS_KEYS))
    discovered = list(
        QBTBatchMove.discover_relevant_fast_resume(
            temp_dir, "T:\\", False, True
        )
    )
    assert discovered == []


def test_regex_patterns_are_not_separator_converted(write_fastresume):
    """Regex mode is left alone on purpose.

    Backslash is an escape character in a pattern, so rewriting separators
    would corrupt sequences like `\\w`. Users opting into `--regex` own the
    separators in their pattern.
    """
    path = write_fastresume(
        "regex.fastresume",
        {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"},
    )
    fast_resume = FastResume(path)
    fast_resume.replace_paths(
        r"/some/(\w+)/.*$",
        r"/\1/regex",
        regex_path=True,
        save_file=False,
        create_backup=False,
    )
    assert fast_resume.save_path == "/test/regex"
    assert fast_resume.qbt_save_path == "/test/regex"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("S:\\Pictures", ["S:\\Pictures", "S:/Pictures"]),
        ("S:/Pictures", ["S:/Pictures", "S:\\Pictures"]),
        ("/torrents", ["/torrents", "\\torrents"]),
        # Nothing to convert, so no extra variants.
        ("plain", ["plain"]),
    ],
)
def test_separator_variants(path, expected):
    assert separator_variants(path) == expected


@pytest.mark.parametrize(
    "value, existing_path, expected",
    [
        ("S:\\Pictures\\a.jpg", "S:\\", True),
        ("S:\\Pictures\\a.jpg", "S:/", True),
        ("S:/Pictures/a.jpg", "S:\\", True),
        ("S:/Pictures/a.jpg", "S:/", True),
        ("T:/Pictures/a.jpg", "S:/", False),
    ],
)
def test_matches_path(value, existing_path, expected):
    assert matches_path(value, existing_path) is expected


def test_replace_path_leaves_non_matching_values_alone():
    assert replace_path("T:/Movies", "S:/", "/mnt/s/") == "T:/Movies"
