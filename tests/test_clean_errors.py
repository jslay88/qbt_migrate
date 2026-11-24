"""Bad input and a failed backup end in a message, not a traceback.

An invalid `-r` pattern raised `re.error` from discovery and a backup zip that
could not be written raised `OSError`; both printed a traceback and exited 1,
which the README reserves for files that could not be read or updated.
"""

import zipfile

import pytest

import qbt_migrate
from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.cli import check_regex, main
from qbt_migrate.exceptions import BackupError, QBTMigrateError
from qbt_migrate.methods import backup_folder


RELEVANT = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}


@pytest.mark.parametrize("dry_run", [(), ("-d",)])
def test_invalid_pattern_is_a_bad_argument(
    write_fastresume, temp_dir, cli_args, caplog, dry_run
):
    """A bad -e pattern exits 2 with a message, writing nothing."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-r", "-e", "(", "-n", "/new", *dry_run)

    assert main() == 2
    assert "-e/--existing-path is not valid with -r/--regex" in caplog.text
    assert "missing )" in caplog.text
    assert "Traceback" not in caplog.text
    assert list(temp_dir.glob("*.zip")) == []
    assert (
        FastResume(temp_dir / "a.fastresume").save_path
        == RELEVANT["save_path"]
    )


def test_invalid_group_reference_is_a_bad_argument(
    write_fastresume, temp_dir, cli_args, caplog
):
    """Used to fail once per file, after the backup had been taken."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args(
        "-b", str(temp_dir), "-r", "-e", "^/some/(test)", "-n", r"/new/\2"
    )

    assert main() == 2
    assert "-n/--new-path is not valid with -r/--regex" in caplog.text
    assert "invalid group reference 2" in caplog.text
    assert list(temp_dir.glob("*.zip")) == []


@pytest.mark.parametrize(
    ("existing", "new", "name"),
    [
        ("a{4294967296}", "/new", "-e/--existing-path"),
        ("^/some/(test)", r"/new/\g<nope>", "-n/--new-path"),
    ],
)
def test_re_errors_outside_re_error_are_caught(
    write_fastresume, temp_dir, cli_args, caplog, existing, new, name
):
    """OverflowError and IndexError from `re` exit 2 like re.error does."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-r", "-e", existing, "-n", new)

    assert main() == 2
    assert f"{name} is not valid with -r/--regex" in caplog.text
    assert list(temp_dir.glob("*.zip")) == []


def test_valid_regex_passes_the_check():
    """Capture groups and backreferences that `re` accepts pass."""
    assert check_regex(r"^/some/(\w+)", r"/new/\1") is None


def test_plain_mode_is_not_parsed_as_regex(
    write_fastresume, temp_dir, cli_args
):
    """Without -r, `(` is just a character in a path."""
    write_fastresume("a.fastresume", {"save_path": "/a(b/x"})
    cli_args("-b", str(temp_dir), "-e", "/a(b", "-n", "/c", "-z")

    assert main() is None
    assert FastResume(temp_dir / "a.fastresume").save_path == "/c/x"


@pytest.fixture
def failing_backup(monkeypatch):
    def _fail(error: OSError) -> None:
        def backup(folder_path, archive_path, include_torrents=True):
            raise error

        monkeypatch.setattr(qbt_migrate.classes, "backup_folder", backup)

    return _fail


def test_backup_failure_raises_before_any_write(
    write_fastresume, temp_dir, failing_backup
):
    """`run` raises BackupError, chained, with every file untouched."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    error = OSError(28, "No space left on device")
    failing_backup(error)

    with pytest.raises(BackupError) as excinfo:
        QBTBatchMove(str(temp_dir)).run("/some/test", "/new")

    assert excinfo.value.error is error
    assert excinfo.value.__cause__ is error
    assert excinfo.value.archive_path.parent == temp_dir
    assert str(excinfo.value).startswith("Could not create the backup")
    assert "No space left on device" in str(excinfo.value)
    assert isinstance(excinfo.value, QBTMigrateError)
    # Callers that caught the bare OSError before still catch it.
    assert isinstance(excinfo.value, OSError)
    assert excinfo.value.errno == 28
    assert (
        FastResume(temp_dir / "a.fastresume").save_path
        == RELEVANT["save_path"]
    )


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(13, "Permission denied"),
        OSError(28, "No space left on device"),
    ],
)
def test_cli_backup_failure_explains_itself(
    write_fastresume, temp_dir, cli_args, caplog, failing_backup, error
):
    """Exit 1 with a message and the -z hint instead of a traceback."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    failing_backup(error)
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new")

    assert main() == 1
    assert "Could not create the backup archive" in caplog.text
    assert error.strerror in caplog.text
    assert "Nothing was changed" in caplog.text
    assert "-z/--skip-backup" in caplog.text
    assert (
        FastResume(temp_dir / "a.fastresume").save_path
        == RELEVANT["save_path"]
    )


def test_partial_archive_is_removed(write_fastresume, temp_dir, monkeypatch):
    """A truncated zip left behind would look like a usable backup."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    archive_path = temp_dir / "backup.zip"

    def write(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(zipfile.ZipFile, "write", write)
    with pytest.raises(OSError, match="No space left"):
        backup_folder(temp_dir, archive_path)

    assert not archive_path.exists()


def test_partial_archive_is_removed_on_any_error(
    write_fastresume, temp_dir, monkeypatch
):
    """zipfile's ValueError for a pre-1980 mtime also removes the archive."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    archive_path = temp_dir / "backup.zip"

    def write(self, *args, **kwargs):
        raise ValueError("ZIP does not support timestamps before 1980")

    monkeypatch.setattr(zipfile.ZipFile, "write", write)
    with pytest.raises(ValueError, match="1980"):
        backup_folder(temp_dir, archive_path)

    assert not archive_path.exists()


def test_partial_archive_cleanup_failure_keeps_the_original_error(
    write_fastresume, temp_dir, monkeypatch
):
    """The disk-full error is reported, not the failed cleanup."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    archive_path = temp_dir / "backup.zip"

    def write(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    def unlink(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(zipfile.ZipFile, "write", write)
    monkeypatch.setattr(type(archive_path), "unlink", unlink)
    with pytest.raises(OSError, match="No space left"):
        backup_folder(temp_dir, archive_path)


def test_existing_file_is_not_removed_when_archive_cannot_be_opened(
    write_fastresume, temp_dir
):
    """Nothing is removed when the archive was never opened."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    archive_path = temp_dir / "backup.zip"
    archive_path.mkdir()  # opening it for writing fails

    with pytest.raises(OSError):
        backup_folder(temp_dir, archive_path)

    assert archive_path.is_dir()
