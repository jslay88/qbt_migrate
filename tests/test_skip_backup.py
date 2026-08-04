"""`-z/--skip-backup`, from #76.

Zipping the whole BT_backup directory on every run is slow with a large
library, and pointless when you are making a series of path changes and already
have a backup from the first pass.
"""

import zipfile

import pytest

from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.cli import main


RELEVANT = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}


def archives(directory) -> list:
    return sorted(directory.glob("fastresume_backup*.zip"))


def test_backup_is_created_by_default(write_fastresume, temp_dir):
    write_fastresume("a.fastresume", dict(RELEVANT))
    QBTBatchMove(str(temp_dir)).run("/some/test", "/new")

    created = archives(temp_dir)
    assert len(created) == 1
    with zipfile.ZipFile(created[0]) as archive:
        assert archive.namelist() == ["a.fastresume"]


def test_no_backup_when_skipped(write_fastresume, temp_dir):
    write_fastresume("a.fastresume", dict(RELEVANT))
    QBTBatchMove(str(temp_dir)).run("/some/test", "/new", create_backup=False)

    assert archives(temp_dir) == []
    assert FastResume(temp_dir / "a.fastresume").save_path == "/new/path"


@pytest.mark.parametrize("flag", ["-z", "--skip-backup"])
def test_cli_skips_the_backup(write_fastresume, temp_dir, cli_args, flag):
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", flag)

    assert main() is None
    assert archives(temp_dir) == []
    assert FastResume(temp_dir / "a.fastresume").save_path == "/new/path"


def test_cli_creates_the_backup_without_the_flag(
    write_fastresume, temp_dir, cli_args
):
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new")

    assert main() is None
    assert len(archives(temp_dir)) == 1


def test_cli_warns_when_skipping(write_fastresume, temp_dir, cli_args, caplog):
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", "-z")

    with caplog.at_level("WARNING", logger="qbt_migrate.cli"):
        main()

    assert "Skipping the backup archive" in caplog.text
