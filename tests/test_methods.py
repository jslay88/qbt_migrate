import re
import tempfile
import zipfile
from pathlib import Path

from qbt_migrate.methods import backup_folder


def test_backup_folder():
    temp_dir = Path(tempfile.mkdtemp())  # Get a tmp dir
    fastresume_file_count = 20  # Number of test fastresume files to build
    torrent_file_count = 20  # Number of test torrent files to build
    invalid_file_count = 20  # Number of invalid files to build

    # Build test files
    for x in range(fastresume_file_count):
        with open(temp_dir / f'test_{x}.fastresume', 'w') as f:
            f.write(f'This is file {x}')

    for x in range(torrent_file_count):
        with open(temp_dir / f'test_{x}.torrent', 'w') as f:
            f.write(f'This is file {x}')

    for x in range(invalid_file_count):
        with open(temp_dir / f'test_{x}.invalid', 'w') as f:
            f.write(f'This is invalid file {x}')

    # 'test.zip' will fail the filename check in archive if it gets archived
    archive_path = temp_dir / 'test.zip'
    backup_folder(temp_dir, archive_path)  # Call backup_folder with torrent files included

    # Validate zip file
    with zipfile.ZipFile(archive_path, 'r') as archive:
        assert(archive.testzip() is None)  # Check no errors
        # Assert that it has the correct file count
        assert(len(archive.infolist()) == fastresume_file_count + torrent_file_count)
        for file in archive.infolist():
            # Get the integer of the file
            filename = re.findall(r'test_(\d+).(?:fastresume)?(?:torrent)?', file.filename)
            assert(len(filename) != 0)  # Ensure we got the integer
            filename = filename[0]
            assert(archive.read(file.filename) == bytes(f'This is file {filename}', 'utf-8'))  # Integrity Check

    archive_path = temp_dir / 'test2.zip'
    backup_folder(temp_dir, archive_path, False)

    # Validate zip file
    with zipfile.ZipFile(archive_path, 'r') as archive:
        assert (archive.testzip() is None)  # Check no errors
        # Assert that it has the correct file count
        assert (len(archive.infolist()) == fastresume_file_count)
        for file in archive.infolist():
            # Get the integer of the file
            filename = re.findall(r'test_(\d+).fastresume', file.filename)
            assert (len(filename) != 0)  # Ensure we got the integer
            filename = filename[0]
            assert (archive.read(file.filename) == bytes(f'This is file {filename}', 'utf-8'))  # Integrity Check
