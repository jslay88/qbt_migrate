"""Plain mode replaces a leading path, once, at a folder boundary.

`-e` is documented as the existing root path. It used to be swapped anywhere it
appeared as a substring, every time, so `-e /data` also rewrote `/srv/data`
and `/database`, and `-e /data -n /mnt/data` was not idempotent.
"""

import pytest

from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.enums import TargetOS
from qbt_migrate.methods import (
    leading_variant,
    matches_path,
    occurs_in,
    replace_path,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param("/data", "/mnt", id="exact"),
        pytest.param("/data/x", "/mnt/x", id="child"),
        pytest.param("\\data\\x", "/mnt\\x", id="other-separator"),
        pytest.param("/srv/data/x", "/srv/data/x", id="mid-path"),
        pytest.param("/database/x", "/database/x", id="no-boundary"),
        pytest.param(
            "/data/backup/data/x", "/mnt/backup/data/x", id="only-once"
        ),
        pytest.param("", "", id="empty-value"),
    ],
)
def test_replace_path_is_anchored(value, expected):
    """Only a leading `/data` ending at a folder boundary, and only once."""
    assert replace_path(value, "/data", "/mnt") == expected


@pytest.mark.parametrize(
    "value, existing_path, expected",
    [
        # The docs/paths.md trailing-separator table.
        ("X:\\Torrents\\movie", "X:\\", "/torrentsTorrents\\movie"),
        ("X:\\Torrents\\movie", "X:", "/torrents\\Torrents\\movie"),
        ("X:\\Torrents\\movie", "X:\\Torrents", "/torrents\\movie"),
        ("X:/Torrents/movie", "X:\\Torrents", "/torrents/movie"),
        ("X:", "X:", "/torrents"),
        # A trailing separator on the pattern is itself the boundary.
        ("/data/x", "/data/", "/torrents" + "x"),
        # ...and it does not match the folder without one.
        ("/data", "/data/", "/data"),
        # Drive roots stored with forward slashes, as newer Windows clients
        # write them.
        ("X:/Torrents/movie", "X:", "/torrents/Torrents/movie"),
        ("X:/Torrents/movie", "X:\\", "/torrentsTorrents/movie"),
        ("X:/", "X:\\", "/torrents"),
        # Matching stays case-sensitive, as it was.
        ("X:\\Torrents\\movie", "x:", "X:\\Torrents\\movie"),
        ("x:/Torrents/movie", "X:", "x:/Torrents/movie"),
    ],
)
def test_trailing_separator_rules_unchanged(value, existing_path, expected):
    """The docs/paths.md trailing-separator table gives the same results."""
    assert replace_path(value, existing_path, "/torrents") == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("/data/x", "/data"),
        ("\\data\\x", "\\data"),
        ("/database", None),
        ("/srv/data", None),
    ],
)
def test_leading_variant(value, expected):
    """Returns the separator form that matched, or None without a boundary."""
    assert leading_variant(value, "/data") == expected


def test_matches_path_needs_a_boundary():
    """Discovery uses the same rule as replacement."""
    assert matches_path("/data/x", "/data") is True
    assert matches_path("/database/x", "/data") is False
    assert matches_path("/srv/data/x", "/data") is False


def test_moving_under_a_new_parent_is_idempotent(write_fastresume):
    """`-e /data -n /mnt/data` twice used to give `/mnt/mnt/data/...`."""
    path = write_fastresume(
        "a.fastresume",
        {
            "save_path": "/data/movies",
            "qBt-savePath": "/data/movies",
            "qBt-downloadPath": "/data/incomplete",
            "mapped_files": ["/data/movies/a.mkv"],
        },
    )
    fast_resume = FastResume(path)
    replace = {
        "existing_path": "/data",
        "new_path": "/mnt/data",
        "target_os": TargetOS.POSIX,
        "save_file": False,
        "create_backup": False,
    }
    fast_resume.replace_paths(**replace)
    after_first_pass = dict(fast_resume._data)
    assert fast_resume.save_path == "/mnt/data/movies"
    assert fast_resume.qbt_download_path == "/mnt/data/incomplete"
    assert fast_resume.mapped_files == ["/mnt/data/movies/a.mkv"]

    fast_resume.replace_paths(**replace)
    assert dict(fast_resume._data) == after_first_pass


def test_replace_paths_leaves_lookalike_paths_alone(write_fastresume):
    """Every key, including `mapped_files`, follows the prefix rule."""
    path = write_fastresume(
        "a.fastresume",
        {
            "save_path": "/data/movies",
            "qBt-savePath": "/data/movies",
            "qBt-downloadPath": "/srv/data/incomplete",
            "mapped_files": ["/database/a.mkv", "/data/backup/data/b.mkv"],
        },
    )
    fast_resume = FastResume(path)
    fast_resume.replace_paths(
        "/data", "/mnt", save_file=False, create_backup=False
    )
    assert fast_resume.save_path == "/mnt/movies"
    assert fast_resume.qbt_download_path == "/srv/data/incomplete"
    assert fast_resume.mapped_files == [
        "/database/a.mkv",
        "/mnt/backup/data/b.mkv",
    ]


def test_discovery_skips_mid_path_and_lookalike_matches(
    write_fastresume, temp_dir
):
    """Torrents under `/srv/data` or `/database` are not picked up."""
    for name, save_path in (
        ("root.fastresume", "/data/movies"),
        ("mid.fastresume", "/srv/data/movies"),
        ("lookalike.fastresume", "/database/movies"),
    ):
        write_fastresume(
            name, {"save_path": save_path, "qBt-savePath": save_path}
        )
    discovered = QBTBatchMove.discover_relevant_fast_resume(
        temp_dir, "/data", False, True
    )
    assert [f.file_path.name for f in discovered] == ["root.fastresume"]


def test_occurs_in():
    """Substring test used only for the hint; None is never a match."""
    assert occurs_in("/home/olduser/dl", "olduser") is True
    assert occurs_in("\\home\\olduser", "home/olduser") is True
    assert occurs_in("/home/other", "olduser") is False
    assert occurs_in(None, "olduser") is False


def test_mid_path_only_points_to_regex(write_fastresume, temp_dir, caplog):
    """`-e olduser` finding nothing at the start says to use `-r`."""
    write_fastresume(
        "a.fastresume",
        {"save_path": "/home/olduser/dl", "qBt-savePath": "/home/olduser/dl"},
    )
    with caplog.at_level("WARNING"):
        discovered = list(
            QBTBatchMove.discover_relevant_fast_resume(
                temp_dir, "olduser", False, True
            )
        )
    assert discovered == []
    assert "use -r" in caplog.text


@pytest.mark.parametrize(
    "existing_path, regex_path",
    [
        pytest.param("/data", False, id="some-found"),
        pytest.param("/elsewhere", False, id="not-anywhere"),
        pytest.param("^olduser", True, id="regex-mode"),
    ],
)
def test_no_regex_hint_otherwise(
    write_fastresume, temp_dir, caplog, existing_path, regex_path
):
    """The hint is only for a plain run that found nothing at all."""
    for name, save_path in (
        ("root.fastresume", "/data/movies"),
        ("mid.fastresume", "/srv/olduser/data/movies"),
    ):
        write_fastresume(
            name, {"save_path": save_path, "qBt-savePath": save_path}
        )
    with caplog.at_level("WARNING"):
        list(
            QBTBatchMove.discover_relevant_fast_resume(
                temp_dir, existing_path, regex_path, True
            )
        )
    assert "use -r" not in caplog.text
