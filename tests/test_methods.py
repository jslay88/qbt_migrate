import re
import tempfile
import zipfile
from pathlib import Path

from qbt_migrate.methods import backup_folder


def test_backup_folder():
    temp_dir = Path(tempfile.mkdtemp())  # Get a tmp dir
    file_count = 20  # Number of test files to build

    # Build test files
    for x in range(file_count):
        with open(temp_dir / f'test_{x}.txt', 'w') as f:
            f.write(f'This is file {x}')

    # 'test.zip' will fail the filename check in archive if it gets archived
    archive_path = temp_dir / 'test.zip'
    backup_folder(temp_dir, archive_path)  # Call backup_folder

    # Validate zip file
    with zipfile.ZipFile(archive_path, 'r') as archive:
        assert(archive.testzip() is None)  # Check no errors
        assert(len(archive.infolist()) == file_count)  # Assert that it has the correct file count
        for file in archive.infolist():
            filename = re.findall(r'test_(\d+).txt', file.filename)  # Get the integer of the file
            assert(len(filename) != 0)  # Ensure we got the integer
            filename = filename[0]
            assert(archive.read(file.filename) == bytes(f'This is file {filename}', 'utf-8'))  # Integrity Check
