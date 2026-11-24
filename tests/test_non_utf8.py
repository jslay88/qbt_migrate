"""Paths that are not valid UTF-8 are bad files, not a crash.

The decoder returns bytes for any string that is not valid UTF-8, and the path
code works on str. A bytes `save_path` or `qBt-savePath` used to raise
`TypeError` inside discovery, which `-s` did not catch, so one legacy file
aborted the whole run with a traceback.
"""

import logging

import pytest

from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.cli import main
from qbt_migrate.exceptions import FastResumeUpdateError


# "Café" in Latin-1, which is not valid UTF-8.
LATIN1 = b"/some/test/Caf\xe9"
GOOD = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}


@pytest.mark.parametrize("key", ["save_path", "qBt-savePath"])
def test_discovery_raises_value_error_naming_the_key(
    write_fastresume, temp_dir, key
):
    """Without -s, discovery stops with an error that names the key."""
    data = dict(GOOD, **{key: LATIN1})
    write_fastresume("a.fastresume", data)

    with pytest.raises(ValueError, match=f"{key} is not valid UTF-8"):
        list(
            QBTBatchMove.discover_relevant_fast_resume(temp_dir, "/some/test")
        )


@pytest.mark.parametrize("key", ["save_path", "qBt-savePath"])
def test_discovery_skips_when_asked(write_fastresume, temp_dir, key, caplog):
    """With -s, the file is skipped and the good one is still found."""
    write_fastresume("a.fastresume", dict(GOOD, **{key: LATIN1}))
    good = write_fastresume("b.fastresume", dict(GOOD))

    with caplog.at_level(logging.WARNING):
        found = list(
            QBTBatchMove.discover_relevant_fast_resume(
                temp_dir, "/some/test", raise_on_error=False
            )
        )

    assert [f.file_path for f in found] == [good]
    assert "a.fastresume" in caplog.text
    assert "not valid UTF-8" in caplog.text


def test_run_with_skip_migrates_the_rest(write_fastresume, temp_dir):
    """A -s run migrates the good file and leaves the bad one as it was."""
    bad = write_fastresume("a.fastresume", dict(GOOD, save_path=LATIN1))
    before = bad.read_bytes()
    good = write_fastresume("b.fastresume", dict(GOOD))

    QBTBatchMove(temp_dir).run(
        "/some/test", "/new", create_backup=False, skip_bad_files=True
    )

    assert bad.read_bytes() == before
    assert FastResume(good).save_path == "/new/path"


# Discovery runs lazily inside the worker pool, so files sorted before the
# bad one are already written when it stops; that holds on master for any
# unreadable file. Only the bad file itself is asserted, in both orders.
@pytest.mark.parametrize("bad_name", ["a.fastresume", "z.fastresume"])
def test_cli_without_skip_exits_1_and_leaves_the_bad_file(
    write_fastresume, temp_dir, cli_args, caplog, bad_name
):
    """Without -s the CLI exits 1 with the hint; the bad file is untouched."""
    bad = write_fastresume(bad_name, dict(GOOD, save_path=LATIN1))
    write_fastresume("b.fastresume", dict(GOOD))
    before = bad.read_bytes()
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", "-z")

    assert main() == 1
    assert bad.read_bytes() == before
    assert "save_path is not valid UTF-8" in caplog.text
    assert "-s/--skip-bad-files" in caplog.text


def test_non_utf8_mapped_files_fails_that_file_only(
    write_fastresume, temp_dir
):
    """A bad mapped_files entry fails that torrent, not the batch."""
    data = dict(GOOD, mapped_files=["ok.mkv", b"Caf\xe9.mkv"])
    bad = write_fastresume("a.fastresume", data)
    before = bad.read_bytes()
    good = write_fastresume("b.fastresume", dict(GOOD))

    with pytest.raises(FastResumeUpdateError) as excinfo:
        QBTBatchMove(temp_dir).run("/some/test", "/new", create_backup=False)

    error = excinfo.value.failures[bad]
    assert isinstance(error, ValueError)
    assert "mapped_files is not valid UTF-8" in str(error)
    assert bad.read_bytes() == before
    assert FastResume(good).save_path == "/new/path"


def test_non_utf8_download_path_fails_that_file_only(
    write_fastresume, temp_dir
):
    """A bad qBt-downloadPath fails that torrent with a named key."""
    bad = write_fastresume(
        "a.fastresume", dict(GOOD, **{"qBt-downloadPath": LATIN1})
    )

    with pytest.raises(FastResumeUpdateError) as excinfo:
        QBTBatchMove(temp_dir).run("/some/test", "/new", create_backup=False)

    assert "qBt-downloadPath is not valid UTF-8" in str(
        excinfo.value.failures[bad]
    )


def test_dry_run_reports_the_failure(write_fastresume, temp_dir):
    """A dry run lists the torrent as failing and writes nothing."""
    data = dict(GOOD, mapped_files=[b"Caf\xe9.mkv"])
    path = write_fastresume("a.fastresume", data)
    before = path.read_bytes()

    summary = QBTBatchMove(temp_dir).plan("/some/test", "/new")

    assert len(summary.plans) == 1
    assert "mapped_files is not valid UTF-8" in summary.plans[0].error
    assert path.read_bytes() == before


def test_unrelated_torrent_with_non_utf8_mapped_files_is_not_bad(
    write_fastresume, temp_dir
):
    """Discovery only checks the keys it reads, so a torrent the run would
    not touch does not stop it."""
    write_fastresume(
        "a.fastresume",
        {"save_path": "/elsewhere", "mapped_files": [b"Caf\xe9.mkv"]},
    )
    good = write_fastresume("b.fastresume", dict(GOOD))

    found = list(
        QBTBatchMove.discover_relevant_fast_resume(temp_dir, "/some/test")
    )

    assert [f.file_path for f in found] == [good]


def test_check_text_paths_accepts_str_and_missing_keys(write_fastresume):
    """Valid UTF-8 and absent keys pass the check."""
    path = write_fastresume(
        "a.fastresume", dict(GOOD, mapped_files=["a.mkv", "b.mkv"])
    )

    FastResume(path).check_text_paths()
