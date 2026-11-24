import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path

import pytest

import qbt_migrate.methods
from qbt_migrate.enums import TargetOS
from qbt_migrate.methods import atomic_write, backup_folder, convert_slashes


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
    backup_folder(
        temp_dir, archive_path
    )  # Call backup_folder with torrent files included

    # Validate zip file
    with zipfile.ZipFile(archive_path, "r") as archive:
        assert archive.testzip() is None  # Check no errors
        # Assert that it has the correct file count
        assert (
            len(archive.infolist())
            == fastresume_file_count + torrent_file_count
        )
        for file in archive.infolist():
            # Get the integer of the file
            filename = re.findall(
                r"test_(\d+).(?:fastresume)?(?:torrent)?", file.filename
            )
            assert len(filename) != 0  # Ensure we got the integer
            filename = filename[0]
            assert archive.read(file.filename) == bytes(
                f"This is file {filename}", "utf-8"
            )  # Integrity Check

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
            assert archive.read(file.filename) == bytes(
                f"This is file {filename}", "utf-8"
            )  # Integrity Check


@pytest.mark.parametrize(
    "path, target_os, expected_path",
    [
        ("C:/some/path", TargetOS.WINDOWS, "C:\\some\\path"),
        ("C:\\some\\path", TargetOS.WINDOWS, "C:\\some\\path"),
        ("\\some\\path\\for\\linux", TargetOS.POSIX, "/some/path/for/linux"),
        ("/some/path/for/linux", TargetOS.POSIX, "/some/path/for/linux"),
        (None, "invalid_os", None),
    ],
)
def test_convert_slashes(path: str, target_os: TargetOS, expected_path: str):
    if target_os == "invalid_os":
        with pytest.raises(ValueError):
            convert_slashes(path, target_os)
    else:
        assert convert_slashes(path, target_os) == expected_path


def test_atomic_write_new_file(temp_dir):
    """A missing target is created, with no temp file left behind."""
    path = temp_dir / "new.fastresume"
    atomic_write(path, b"d1:ai1ee")
    assert path.read_bytes() == b"d1:ai1ee"
    assert list(temp_dir.iterdir()) == [path]


def test_atomic_write_keeps_mode(temp_dir):
    """The replaced file keeps the original's permission bits."""
    path = temp_dir / "a.fastresume"
    path.write_bytes(b"old")
    os.chmod(path, 0o640)
    atomic_write(str(path), b"new")
    assert path.read_bytes() == b"new"
    if os.name != "nt":  # Windows only has a read-only bit
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert list(temp_dir.iterdir()) == [path]


@pytest.mark.skipif(os.name == "nt", reason="needs symlink privileges")
def test_atomic_write_through_symlink(temp_dir):
    """A symlink stays a symlink; the file it points to gets the data."""
    target = temp_dir / "target.fastresume"
    target.write_bytes(b"old")
    link = temp_dir / "link.fastresume"
    link.symlink_to(target)
    atomic_write(link, b"new")
    assert link.is_symlink()
    assert target.read_bytes() == b"new"


def _fake_owner(monkeypatch, path, uid, gid):
    """Make `path` look owned by uid:gid to os.stat."""
    real_stat = os.stat

    def fake_stat(p, *args, **kwargs):
        st = real_stat(p, *args, **kwargs)
        if os.fspath(p) == os.fspath(path):
            values = list(st)
            values[stat.ST_UID] = uid
            values[stat.ST_GID] = gid
            return os.stat_result(values)
        return st

    monkeypatch.setattr(os, "stat", fake_stat)


def test_atomic_write_keeps_owner(monkeypatch, temp_dir):
    """A file owned by someone else is chowned back to that owner."""
    path = temp_dir / "a.fastresume"
    path.write_bytes(b"old")
    _fake_owner(monkeypatch, path, 99, 100)
    calls = []
    monkeypatch.setattr(
        qbt_migrate.methods.os,
        "chown",
        lambda p, uid, gid: calls.append((uid, gid)),
        raising=False,
    )
    atomic_write(path, b"new")
    assert calls == [(99, 100)]
    assert path.read_bytes() == b"new"


def test_atomic_write_keeps_group_when_owner_refused(
    monkeypatch, temp_dir, caplog
):
    """As non-root, the group is still kept, and that is not a warning."""
    path = temp_dir / "a.fastresume"
    path.write_bytes(b"old")
    _fake_owner(monkeypatch, path, 99, 100)
    calls = []

    def chown(p, uid, gid):
        calls.append((uid, gid))
        if uid != -1:
            raise PermissionError("Operation not permitted")

    monkeypatch.setattr(qbt_migrate.methods.os, "chown", chown, raising=False)
    monkeypatch.setattr(qbt_migrate.methods, "_owner_warned", False)
    with caplog.at_level("DEBUG", logger="qbt_migrate.methods"):
        atomic_write(path, b"new")
    assert calls == [(99, 100), (-1, 100)]
    assert path.read_bytes() == b"new"
    assert "Kept the group" in caplog.text
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_atomic_write_owner_not_allowed(monkeypatch, temp_dir, caplog):
    """A refused chown warns once per run and every save still goes through."""
    paths = [temp_dir / "a.fastresume", temp_dir / "b.fastresume"]
    for path in paths:
        path.write_bytes(b"old")
    real_stat = os.stat

    def fake_stat(p, *args, **kwargs):
        st = real_stat(p, *args, **kwargs)
        if os.fspath(p) in map(os.fspath, paths):
            values = list(st)
            values[stat.ST_UID] = 99
            values[stat.ST_GID] = 100
            return os.stat_result(values)
        return st

    def deny(*_):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(qbt_migrate.methods.os, "chown", deny, raising=False)
    monkeypatch.setattr(qbt_migrate.methods, "_owner_warned", False)
    with caplog.at_level("DEBUG", logger="qbt_migrate.methods"):
        for path in paths:
            atomic_write(path, b"new")
    assert [p.read_bytes() for p in paths] == [b"new", b"new"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "Could not keep the owner" in warnings[0].getMessage()
    assert caplog.text.count("Could not keep the owner") == 2
    assert sorted(temp_dir.iterdir()) == paths


@pytest.mark.skipif(
    not hasattr(os, "getuid") or os.getuid() != 0, reason="needs root"
)
def test_atomic_write_keeps_owner_as_root(temp_dir):
    """Real chown, no mocks: the Docker-as-root case."""
    path = temp_dir / "a.fastresume"
    path.write_bytes(b"old")
    os.chown(path, 99, 100)
    atomic_write(path, b"new")
    st = path.stat()
    assert (st.st_uid, st.st_gid) == (99, 100)


@pytest.mark.parametrize(
    "name, error",
    [
        ("replace", OSError("No space left on device")),
        ("fsync", KeyboardInterrupt()),
    ],
)
def test_atomic_write_failure_cleans_up(monkeypatch, temp_dir, name, error):
    """A failure mid-write keeps the old file and removes the temp file."""
    path = temp_dir / "a.fastresume"
    path.write_bytes(b"old")

    def fail(*_):
        raise error

    monkeypatch.setattr(qbt_migrate.methods.os, name, fail)
    with pytest.raises(type(error)):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert list(temp_dir.iterdir()) == [path]


def test_atomic_write_failure_removes_read_only_temp(monkeypatch, temp_dir):
    """Cleanup clears read-only first, which Windows needs to delete it."""
    path = temp_dir / "a.fastresume"
    path.write_bytes(b"old")
    os.chmod(path, 0o444)
    real_chmod, real_unlink = os.chmod, os.unlink
    modes = {}

    def chmod(p, mode, *args, **kwargs):
        modes[os.fspath(p)] = mode
        real_chmod(p, mode, *args, **kwargs)

    def unlink(p, *args, **kwargs):
        # What DeleteFile does with the read-only attribute set.
        if not modes.get(os.fspath(p), stat.S_IWRITE) & stat.S_IWRITE:
            raise PermissionError("Access is denied")
        real_unlink(p, *args, **kwargs)

    def fail(*_):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(qbt_migrate.methods.os, "chmod", chmod)
    monkeypatch.setattr(qbt_migrate.methods.os, "unlink", unlink)
    monkeypatch.setattr(qbt_migrate.methods.os, "replace", fail)
    with pytest.raises(PermissionError):
        atomic_write(path, b"new")
    real_chmod(path, 0o644)
    assert path.read_bytes() == b"old"
    assert list(temp_dir.iterdir()) == [path]
