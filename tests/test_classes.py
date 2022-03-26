import glob
import os
import posixpath
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from bencodepy.exceptions import BencodeDecodeError

import qbt_migrate
from qbt_migrate.classes import FastResume, QBTBatchMove


@pytest.fixture
def linux_env(monkeypatch):
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "path", posixpath)


@pytest.fixture
def temp_dir():
    temp_dir = Path(tempfile.mkdtemp())  # Get a tmp dir
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_file(mode="w"):
    temp_file = tempfile.mktemp()
    with open(temp_file, mode) as f:
        yield temp_file, f
    os.remove(temp_file)


@pytest.mark.parametrize(
    "bt_backup_path, expected_bt_backup_path",
    [(None, "/home/test/.local/share/data/qBittorrent/BT_backup"), ("/some/path", "/some/path")],
)
def test_qbt_batch_move_init(linux_env, bt_backup_path, expected_bt_backup_path):
    qbt = QBTBatchMove(bt_backup_path)
    assert qbt.bt_backup_path == expected_bt_backup_path
    assert isinstance(qbt.discovered_files, set)


def test_qbt_batch_move_discover_relevant_fast_resume(temp_dir):
    fast_resume_files = list(QBTBatchMove.discover_relevant_fast_resume(temp_dir, "", True))
    assert fast_resume_files == []

    for file in glob.glob("./tests/test_files/good*.fastresume"):
        file = Path(file)
        print(f"Copying {file} to {temp_dir / file.name}")
        shutil.copy(file, temp_dir / file.name)
    fast_resume_files = list(QBTBatchMove.discover_relevant_fast_resume(temp_dir, "", True))
    assert len(fast_resume_files) == 2
    fast_resume_files = list(QBTBatchMove.discover_relevant_fast_resume(temp_dir, "/some/test", True))
    assert len(fast_resume_files) == 1
    assert fast_resume_files[0].save_path.startswith("/some/test") is True

    for file in glob.glob("./tests/test_files/bad*.fastresume"):
        file = Path(file)
        print(f"Copying {file} to {temp_dir / file.name}")
        shutil.copy(file, temp_dir / file.name)
    with pytest.raises(BencodeDecodeError):
        list(QBTBatchMove.discover_relevant_fast_resume(temp_dir, "/some/test", True))

    fast_resume_files = list(QBTBatchMove.discover_relevant_fast_resume(temp_dir, "/some/test", False))
    assert len(fast_resume_files) == 1


def test_qbt_batch_move_run_not_a_dir(temp_file):
    # Test path not exists
    qbt = QBTBatchMove("/not/a/valid/path")
    pytest.raises(NotADirectoryError, qbt.run, "existing_path", "new_path")

    # Test path exists, but not a directory
    qbt = QBTBatchMove(temp_file[0])
    pytest.raises(NotADirectoryError, qbt.run, "existing_path", "new_path")


def test_qbt_batch_move_run_create_backup_and_backup_folder(monkeypatch, temp_dir):
    class MockCaller:
        def __init__(self):
            self.called = False

        def mock_create_backup(self, directory: str, archive: str):
            self.called = True
            assert directory == temp_dir
            assert archive.startswith(os.path.join(temp_dir, "fastresume_backup"))
            assert archive.endswith(".zip")

    mock = MockCaller()
    monkeypatch.setattr(qbt_migrate.classes, "backup_folder", mock.mock_create_backup)

    qbt = QBTBatchMove(temp_dir)
    qbt.run("existing_path", "new_path", create_backup=False)
    assert mock.called is False  # Test `backup_folder` is not called
    qbt.run("existing_path", "new_path", create_backup=True)
    assert mock.called is True  # Test `backup_folder` is called

    mock.called = False  # Reset MockCaller
    qbt = QBTBatchMove(temp_dir)
    qbt.backup_folder(temp_dir, os.path.join(temp_dir, "fastresume_backup.zip"))
    assert mock.called is True


def test_qbt_batch_move_run_replace_paths(monkeypatch, temp_dir):
    class MockFastResume(FastResume):
        def __init__(self, *_, **__):
            self.called = False
            self._data = {"save_path": "existing_path", "qBt-savePath": "existing_path"}

        def replace_paths(self, *_, **__):
            self.called = True

    with open(temp_dir / "test.fastresume", "w") as _:
        pass

    monkeypatch.setattr(qbt_migrate.classes, "FastResume", MockFastResume)

    qbt = QBTBatchMove(temp_dir)
    qbt.run("existing", "new", create_backup=False)
    assert len(qbt.discovered_files) == 1
    for fast_resume in qbt.discovered_files:
        assert fast_resume.called


def test_qbt_batch_move_update_fastresume(monkeypatch):
    class MockFastResume(FastResume):
        def __init__(self):
            self.called = False

        def replace_paths(self, *_, **__):
            self.called = True

    mock_fast_resume = MockFastResume()
    QBTBatchMove.update_fastresume(mock_fast_resume, "existing_path", "new_path")
    assert mock_fast_resume.called

    pytest.raises(
        TypeError, qbt_migrate.classes.QBTBatchMove.update_fastresume, "not_fast_resume_object", "existing", "new"
    )


def test_fastresume_init(temp_dir):
    for file in glob.glob("./tests/test_files/good*.fastresume"):
        file = Path(file)
        print(f"Copying {file} to {temp_dir / file.name}")
        shutil.copy(file, temp_dir / file.name)
        fast_resume = FastResume(temp_dir / file.name)
        assert fast_resume.save_path is not None

    with pytest.raises(FileNotFoundError):
        FastResume("/not/a/valid/file")


def test_fastresume_properties(temp_dir):
    for file in glob.glob("./tests/test_files/good*.fastresume"):
        file = Path(file)
        print(f"Copying {file} to {temp_dir / file.name}")
        shutil.copy(file, temp_dir / file.name)
        fast_resume = FastResume(temp_dir / file.name)
        assert fast_resume.file_path == str(temp_dir / file.name)
        assert fast_resume.backup_filename.startswith(str(temp_dir / file.name))
        assert fast_resume.backup_filename.endswith(".bkup")
        assert fast_resume.save_path == fast_resume._data["save_path"]
        assert fast_resume.qbt_save_path == fast_resume._data["qBt-savePath"]
        assert (
            fast_resume.mapped_files == fast_resume._data["mapped_files"]
            if "mapped_files" in fast_resume._data
            else fast_resume.mapped_files is None
        )


class MockFastResumeSaveCaller:
    """
    Simple mock caller for `FastResume.save` method that provides minimal tracking
    """

    def __init__(self):
        self.called = False
        self.saved_file_names = set()

    def mock_save(self, fn=None):
        self.called = True
        if fn is not None:
            self.saved_file_names.add(fn)

    def mock_write(self, _, fn):
        self.mock_save(fn)

    def reset(self):
        self.__init__()


def test_fastresume_set_save_path(monkeypatch):
    fast_resume = FastResume("./tests/test_files/good.fastresume")
    mock = MockFastResumeSaveCaller()
    monkeypatch.setattr(fast_resume, "save", mock.mock_save)

    # Test invalid save key
    with pytest.raises(KeyError):
        fast_resume.set_save_path("/a/path", "not-a-valid-key")
    # Explicitly test setting of key
    fast_resume.set_save_path("/this/is/a/test", save_file=False, create_backup=False)
    fast_resume.set_save_path("/this/is/a/test", key="qBt-savePath", save_file=False, create_backup=False)
    assert fast_resume.save_path == "/this/is/a/test"
    assert fast_resume.qbt_save_path == "/this/is/a/test"

    mock.reset()
    # Test target_os None
    fast_resume.set_save_path("/target\\is/none", save_file=False, create_backup=False)
    assert fast_resume.save_path == "/target\\is/none"
    # Test target_os windows
    fast_resume.set_save_path("C:/target/windows", target_os="windows", save_file=False, create_backup=False)
    assert fast_resume.save_path == "C:\\target\\windows"
    # Test target_os linux
    fast_resume.set_save_path("\\target\\linux", target_os="linux", save_file=False, create_backup=False)
    assert fast_resume.save_path == "/target/linux"
    # Test target_os mac
    fast_resume.set_save_path("\\target\\mac", target_os="mac", save_file=False, create_backup=False)
    assert fast_resume.save_path == "/target/mac"

    mock.reset()
    # Test save_file
    fast_resume.set_save_path("/this/is/a/test", save_file=True, create_backup=False)
    assert mock.called is True
    assert len(mock.saved_file_names) == 0

    mock.reset()
    # Test create_backup=False
    fast_resume.set_save_path("test", save_file=False, create_backup=False)
    assert mock.called is False
    # Test create_backup=True
    fast_resume.set_save_path("test", save_file=False, create_backup=True)
    assert mock.called
    assert len(mock.saved_file_names) == 1
    for file_name in mock.saved_file_names:
        assert "good.fastresume." in file_name
        assert file_name.endswith(".bkup")


def test_fastresume_set_save_paths(monkeypatch):
    fast_resume = FastResume("./tests/test_files/good.fastresume")
    mock = MockFastResumeSaveCaller()
    monkeypatch.setattr(fast_resume, "save", mock.mock_save)

    # Test empty path ValueError
    with pytest.raises(ValueError):
        fast_resume.set_save_paths("", create_backup=False, save_file=False)
    # Test default call
    fast_resume.set_save_paths("/this/is/a/path")
    assert fast_resume.save_path == "/this/is/a/path"
    assert fast_resume.qbt_save_path == "/this/is/a/path"
    # Test with differing qBt-savePath
    fast_resume.set_save_paths("/this/is/a/path", "/this/is/a/qbt/path")
    assert fast_resume.save_path == "/this/is/a/path"
    assert fast_resume.qbt_save_path == "/this/is/a/qbt/path"

    # Test mapped_files convert slashes (replacing of paths happens with `replace_paths`)
    fast_resume.set_save_paths("C:/this/is/a/path", target_os="windows")
    assert len(fast_resume.mapped_files) > 0
    for mapped_file in fast_resume.mapped_files:
        assert mapped_file.startswith("\\some\\test\\path\\")


def test_fastresume_save(monkeypatch):
    fast_resume = FastResume("./tests/test_files/good.fastresume")
    mock = MockFastResumeSaveCaller()
    monkeypatch.setattr(qbt_migrate.classes.bencode, "write", mock.mock_write)

    # Test default call
    fast_resume.save()
    assert mock.called
    assert len(mock.saved_file_names) == 1
    for file_name in mock.saved_file_names:
        assert file_name.endswith("good.fastresume")

    mock.reset()
    # Test calling with file name
    fast_resume.save("test_file")
    assert mock.called
    assert len(mock.saved_file_names) == 1
    for file_name in mock.saved_file_names:
        assert file_name == "test_file"


def test_fastresume_replace_paths(monkeypatch):
    fast_resume = FastResume("./tests/test_files/good.fastresume")
    fast_resume.replace_paths("/some/test", "/a/new/test", save_file=False, create_backup=False)
    assert fast_resume.save_path == "/a/new/test/path"
    assert fast_resume.qbt_save_path == "/a/new/test/path"
    assert len(fast_resume.mapped_files) > 0
    for mapped_file in fast_resume.mapped_files:
        assert mapped_file.startswith("/a/new/test/path")
