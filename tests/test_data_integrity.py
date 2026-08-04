"""Edge cases where the tool used to quietly write wrong data."""

import sys
import zipfile

import pytest

from qbt_migrate.classes import FastResume
from qbt_migrate.enums import TargetOS
from qbt_migrate.methods import backup_folder, discover_bt_backup_path


def test_no_path_keys_raises_instead_of_writing_none(write_fastresume):
    """`str(None)` used to be written as the literal string "None".

    `replace_paths` passed `path=str(new_save_path)`, and `"None"` sails
    straight through the `if not path.strip()` guard, so a fastresume with
    neither path key ended up with `save_path = "None"`.
    """
    path = write_fastresume(
        "no_paths.fastresume", {"mapped_files": ["/some/test/path/a.mkv"]}
    )
    fast_resume = FastResume(path)
    with pytest.raises(ValueError, match="Cannot set an empty save path"):
        fast_resume.replace_paths(
            "/some/test", "/new", save_file=False, create_backup=False
        )
    assert fast_resume.save_path != "None"


def test_rejected_path_leaves_no_backup_behind(write_fastresume, temp_dir):
    """Validation happens before the .bkup is written, not after."""
    path = write_fastresume(
        "reject.fastresume", {"save_path": "/some/test/path"}
    )
    fast_resume = FastResume(path)
    with pytest.raises(ValueError):
        fast_resume.set_save_paths("   ", create_backup=True, save_file=False)
    assert list(temp_dir.glob("*.bkup")) == []


def test_distinct_download_path_is_preserved(write_fastresume):
    """A separate incomplete-downloads directory must not be clobbered.

    `set_save_paths` used to fall through to
    `set_save_path(self.qbt_save_path, key="qBt-downloadPath")`, overwriting an
    intentionally different location with the save path.
    """
    path = write_fastresume(
        "dl.fastresume",
        {
            "save_path": "/done",
            "qBt-savePath": "/done",
            "qBt-downloadPath": "/incomplete",
        },
    )
    fast_resume = FastResume(path)
    fast_resume.set_save_paths(
        "/new/done", save_file=False, create_backup=False
    )
    assert fast_resume.save_path == "/new/done"
    assert fast_resume.qbt_download_path == "/incomplete"


def test_untouched_download_path_still_converts_slashes(write_fastresume):
    """Preserving the value must not skip the target OS conversion."""
    path = write_fastresume(
        "dl.fastresume",
        {
            "save_path": "D:\\done",
            "qBt-savePath": "D:\\done",
            "qBt-downloadPath": "E:\\incomplete",
        },
    )
    fast_resume = FastResume(path)
    fast_resume.set_save_paths(
        "/mnt/d/done",
        target_os=TargetOS.POSIX,
        save_file=False,
        create_backup=False,
    )
    assert fast_resume.qbt_download_path == "E:/incomplete"


def test_replace_paths_rewrites_distinct_download_path(write_fastresume):
    path = write_fastresume(
        "dl.fastresume",
        {
            "save_path": "D:\\Torrents\\done",
            "qBt-savePath": "D:\\Torrents\\done",
            "qBt-downloadPath": "D:\\Torrents\\incomplete",
        },
    )
    fast_resume = FastResume(path)
    fast_resume.replace_paths(
        "D:\\Torrents",
        "/torrents",
        target_os=TargetOS.POSIX,
        save_file=False,
        create_backup=False,
    )
    assert fast_resume.save_path == "/torrents/done"
    assert fast_resume.qbt_download_path == "/torrents/incomplete"


def test_backup_archive_entries_are_flat(temp_dir):
    """Entries used to carry the whole source path minus the leading slash.

    Restoring meant digging files out of a nested tree mirroring the machine
    the backup was taken on.
    """
    (temp_dir / "a.fastresume").write_text("a")
    (temp_dir / "a.torrent").write_text("t")
    (temp_dir / "notes.txt").write_text("ignored")

    archive_path = temp_dir / "backup.zip"
    backup_folder(temp_dir, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == ["a.fastresume", "a.torrent"]
        assert archive.read("a.fastresume") == b"a"


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_discover_bt_backup_path_without_env_vars(monkeypatch, platform):
    """Unset HOME or LOCALAPPDATA used to raise TypeError.

    `Path(os.getenv("HOME"), ...)` fails with "argument should be a str or an
    os.PathLike object where __fspath__ returns a str, not 'NoneType'".
    """
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", platform)

    path = discover_bt_backup_path()
    assert path.name == "BT_backup"
    assert "qBittorrent" in path.parts
