"""Discovery also looks at `qBt-downloadPath`.

It is the incomplete-downloads folder, often a different disk from the save
path. A torrent whose download path was under the old root but whose save path
was not used to be skipped, so its download path kept the old value.
"""

import logging

import pytest

from qbt_migrate.classes import FastResume, QBTBatchMove


ELSEWHERE = {"save_path": "/data/done", "qBt-savePath": "/data/done"}


def discover(temp_dir, existing_path, regex_path=False):
    return list(
        QBTBatchMove.discover_relevant_fast_resume(
            temp_dir, existing_path, regex_path
        )
    )


def test_download_path_alone_makes_a_torrent_relevant(
    write_fastresume, temp_dir
):
    """A download path under the old root is enough to be found."""
    path = write_fastresume(
        "a.fastresume", dict(ELSEWHERE, **{"qBt-downloadPath": "/old/inc"})
    )

    assert [f.file_path for f in discover(temp_dir, "/old")] == [path]


def test_download_path_matches_either_separator(write_fastresume, temp_dir):
    """The download path is matched under both separator conventions."""
    path = write_fastresume(
        "a.fastresume",
        dict(ELSEWHERE, **{"qBt-downloadPath": "X:\\Incomplete\\a"}),
    )

    assert [f.file_path for f in discover(temp_dir, "X:/")] == [path]


def test_download_path_matches_in_regex_mode(write_fastresume, temp_dir):
    """Regex mode searches the download path as well."""
    path = write_fastresume(
        "a.fastresume", dict(ELSEWHERE, **{"qBt-downloadPath": "/old/inc"})
    )

    found = discover(temp_dir, r"^/ol(d)", regex_path=True)

    assert [f.file_path for f in found] == [path]


def test_unrelated_download_path_is_still_not_relevant(
    write_fastresume, temp_dir, caplog
):
    """A download path elsewhere does not make a torrent relevant."""
    write_fastresume(
        "a.fastresume", dict(ELSEWHERE, **{"qBt-downloadPath": "/other"})
    )

    with caplog.at_level(logging.DEBUG, logger="qbt_migrate.classes"):
        assert discover(temp_dir, "/old") == []

    assert "qBt-downloadPath: /other" in caplog.text


@pytest.mark.parametrize("regex_path", [False, True])
def test_non_utf8_download_path_is_ignored(
    write_fastresume, temp_dir, regex_path
):
    """A download path that is not UTF-8 is not matched and does not crash."""
    write_fastresume(
        "a.fastresume",
        dict(ELSEWHERE, **{"qBt-downloadPath": b"/old/Caf\xe9"}),
    )
    good = write_fastresume(
        "b.fastresume", dict(ELSEWHERE, **{"qBt-downloadPath": "/old/inc"})
    )

    found = discover(temp_dir, "/old", regex_path=regex_path)

    assert [f.file_path for f in found] == [good]


def test_run_moves_only_the_download_path(write_fastresume, temp_dir):
    """Found by download path, only that key is rewritten."""
    path = write_fastresume(
        "a.fastresume", dict(ELSEWHERE, **{"qBt-downloadPath": "/old/inc"})
    )

    QBTBatchMove(temp_dir).run("/old/", "/new/", create_backup=False)

    migrated = FastResume(path)
    assert migrated.qbt_download_path == "/new/inc"
    assert migrated.save_path == "/data/done"
    assert migrated.qbt_save_path == "/data/done"


def test_dry_run_lists_the_download_path_change(write_fastresume, temp_dir):
    """A dry run shows the one change and writes nothing."""
    path = write_fastresume(
        "a.fastresume", dict(ELSEWHERE, **{"qBt-downloadPath": "/old/inc"})
    )
    before = path.read_bytes()

    summary = QBTBatchMove(temp_dir).plan("/old/", "/new/")

    assert len(summary.plans) == 1
    changes = {c.key: (c.old, c.new) for c in summary.plans[0].changes}
    assert changes == {"qBt-downloadPath": ("/old/inc", "/new/inc")}
    assert path.read_bytes() == before
