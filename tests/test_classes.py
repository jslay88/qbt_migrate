import glob
import os
import posixpath
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from bencodepy.exceptions import BencodeDecodeError

from qbt_migrate.classes import QBTBatchMove


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


@pytest.mark.parametrize(
    "bt_backup_path, expected_bt_backup_path",
    [(None, "/home/test/.local/share/data/qBittorrent/BT_backup"), ("/some/path", "/some/path")],
)
def test_qbt_batch_move_init(linux_env, bt_backup_path, expected_bt_backup_path):
    qbt = QBTBatchMove(bt_backup_path)
    assert qbt.bt_backup_path == expected_bt_backup_path


def test_qbt_batch_move_discover_relevant_fast_resume(temp_dir):
    print("RUNNING")
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
        fast_resume_files = list(QBTBatchMove.discover_relevant_fast_resume(temp_dir, "/some/test", True))

    fast_resume_files = list(QBTBatchMove.discover_relevant_fast_resume(temp_dir, "/some/test", False))
    assert len(fast_resume_files) == 1
