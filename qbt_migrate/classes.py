import logging
import os
import re
from datetime import datetime
from threading import Thread
from typing import Optional

import bencodepy
<<<<<<< HEAD

# encoding: "utf-8", to attempt to encode to utf-8 which converts normal strings for python
# encoding_fallback: "all", will fallback to using binary if utf-8 fails at any part
bencode = bencodepy.Bencode(encoding="utf-8", encoding_fallback="all")
=======
from bencodepy.exceptions import BencodeDecodeError
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21

from .methods import backup_folder, convert_slashes, discover_bt_backup_path


logger = logging.getLogger(__name__)
bencode = bencodepy.Bencode(encoding="utf-8", encoding_fallback="all")


class QBTBatchMove(object):
    logger = logging.getLogger(__name__ + ".QBTBatchMove")

    def __init__(self, bt_backup_path: str = None):
        if bt_backup_path is None:
            bt_backup_path = discover_bt_backup_path()
<<<<<<< HEAD
        self.logger.debug('BT_backup Path: %s', bt_backup_path)
=======
        self.logger.debug(f"BT_backup Path: {bt_backup_path}")
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21
        self.bt_backup_path = bt_backup_path
        self.discovered_files = set()

    def run(
        self,
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: Optional[str] = None,
        create_backup: bool = True,
        skip_bad_files: bool = False,
    ):
        """
        Perform Batch Processing of path changes.
        :param existing_path: Existing path to look for
        :type existing_path: str
        :param new_path: New Path to replace with
        :type new_path: str
        :param regex_path: Existing and New Paths are regex patterns with capture groups
        :type regex_path: bool
        :param target_os: If targeting a different OS than the source. Must be Windows, Linux, or Mac.
        :type target_os: str
        :param create_backup: Create a backup archive of the BT_backup directory?
        :type create_backup: bool
        :param skip_bad_files: Skip .fastresume files that cannot be read successfully.
        :type skip_bad_files: bool
        """
        if not os.path.exists(self.bt_backup_path) or not os.path.isdir(self.bt_backup_path):
            raise NotADirectoryError(self.bt_backup_path)
        if create_backup:
            backup_filename = f'fastresume_backup{datetime.now().strftime("%Y%m%d%H%M%S")}.zip'
<<<<<<< HEAD
            self.backup_folder(self.bt_backup_path,
                               os.path.join(os.path.dirname(self.bt_backup_path), backup_filename))

        self.logger.info('Searching for .fastresume files with path %s ...', existing_path)
        for fast_resume in self.discover_relevant_fast_resume(self.bt_backup_path, existing_path, not skip_bad_files):
=======
            backup_folder(self.bt_backup_path, os.path.join(self.bt_backup_path, backup_filename))

        self.logger.info(f"Searching for .fastresume files with path {existing_path} ...")
        for fast_resume in self.discover_relevant_fast_resume(
            self.bt_backup_path, existing_path, regex_path, not skip_bad_files
        ):
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21
            # Fire and forget
            self.discovered_files.add(fast_resume)
            Thread(
                target=fast_resume.replace_paths, args=[existing_path, new_path, regex_path, target_os, True, False]
            ).start()

    @classmethod
    def discover_relevant_fast_resume(
        cls, bt_backup_path: str, existing_path: str, regex_path: bool = False, raise_on_error: bool = True
    ):
        """
        Find .fastresume files that contain the existing path.
        :param bt_backup_path: Path to BT_backup folder
        :type bt_backup_path: str
        :param existing_path: The existing path to look for
        :type existing_path: str
        :param regex_path: Existing Path is a regex pattern with capture groups
        :type: bool
        :param raise_on_error: Raise if error parsing .fastresume files
        :type raise_on_error: bool
        :return: List of FastResume Objects
        :rtype: list[FastResume]
        """
        for file in os.listdir(bt_backup_path):
            if file.endswith(".fastresume"):
                try:
                    fast_resume = FastResume(os.path.join(bt_backup_path, file))
<<<<<<< HEAD
                except (
                    bencodepy.exceptions.BencodeDecodeError,
                    FileNotFoundError,
                    ValueError
                ) as e:
=======
                except (BencodeDecodeError, FileNotFoundError, ValueError) as e:
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21
                    if raise_on_error:
                        cls.logger.critical(f"Unable to parse {file}. Stopping Discovery!")
                        raise e
                    cls.logger.warning(f"Unable to parse {file}. Skipping!\n\n{e}")
                    continue
                if (fast_resume.save_path is not None and existing_path in fast_resume.save_path) or (
                    fast_resume.qbt_save_path is not None and existing_path in fast_resume.qbt_save_path
                ):
                    yield fast_resume
                elif regex_path and (
                    (fast_resume.save_path is not None and re.match(existing_path, fast_resume.save_path))
                    or (fast_resume.qbt_save_path is not None and re.match(existing_path, fast_resume.qbt_save_path))
                ):
                    yield fast_resume
        return

    @classmethod
    def backup_folder(cls, folder_path: str, archive_path: str):
<<<<<<< HEAD
        cls.logger.info(f'Creating Archive {archive_path} ...')
        files_to_archive = os.listdir(folder_path)
        with zipfile.ZipFile(archive_path, 'w') as archive:
            for file in files_to_archive:
                archive.write(os.path.join(folder_path, file))
        cls.logger.info('Done!')
=======
        return backup_folder(folder_path, archive_path)
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21

    @classmethod
    def update_fastresume(
        cls,
        fast_resume: "FastResume",
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: Optional[str] = None,
        save_file: bool = True,
        create_backup: bool = True,
    ):
        if not isinstance(fast_resume, FastResume):
            raise TypeError("Not a FastResume object, cannot replace paths!")
        fast_resume.replace_paths(existing_path, new_path, regex_path, target_os, save_file, create_backup)


class FastResume(object):
    logger = logging.getLogger(__name__ + ".FastResume")

    def __init__(self, file_path: str):
        self._file_path = os.path.realpath(file_path)
        if not os.path.exists(self.file_path) or not os.path.isfile(self.file_path):
            raise FileNotFoundError(self.file_path)
<<<<<<< HEAD
        self.logger.debug(f'Loading Fast Resume: {self.file_path}')
        self._data = bencode.read(self.file_path)
        if 'save_path' not in self._data or 'qBt-savePath' not in self._data:
            raise ValueError('Missing required keys for a qBittorrent .fastresume file')
        self.logger.debug(f'Fast Resume ({self.file_path}) Init Complete.')
=======
        self.logger.debug(f"Loading Fast Resume: {self.file_path}")
        self._data = bencode.read(self.file_path)
        self.logger.debug(f"Fast Resume ({self.file_path}) Init Complete.")
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21

    @property
    def file_path(self) -> str:
        return self._file_path

    @property
<<<<<<< HEAD
    def backup_filename(self):
=======
    def backup_filename(self) -> str:
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21
        return f'{self.file_path}.{datetime.now().strftime("%Y%m%d%H%M%S")}.bkup'

    @property
    def save_path(self) -> Optional[str]:
        if "save_path" in self._data:
            return self._data["save_path"]

    @property
    def qbt_save_path(self) -> Optional[str]:
        if "qBt-savePath" in self._data:
            return self._data["qBt-savePath"]

    @property
    def mapped_files(self):
        if "mapped_files" in self._data:
            return self._data["mapped_files"]

    def set_save_path(
        self,
        path: str,
        key: str = "save_path",
        target_os: Optional[str] = None,
        save_file: bool = True,
        create_backup: bool = True,
    ):
        if key not in ["save_path", "qBt-savePath"]:
            raise KeyError("When setting a save path, key must be `save_path` or `qBt-savePath`. " f"Received {key}")
        if create_backup:
            self.save(self.backup_filename)
        if target_os is not None:
            path = convert_slashes(path, target_os)
        self.logger.debug(f"Setting {key}... Old: {self._data.get(key, None)}, New: {path}, Target OS: {target_os}")
        self._data[key] = path
        if save_file:
            self.save()

    def set_save_paths(
        self,
        path: str,
        qbt_path: Optional[str] = None,
        target_os: Optional[str] = None,
        save_file: bool = True,
        create_backup: bool = True,
    ):
        if create_backup:
            self.save(self.backup_filename)
        if not path.strip():
            raise ValueError("Cannot set empty paths!")
        self.set_save_path(path, key="save_path", target_os=target_os, save_file=False, create_backup=False)
        qbt_path = path if qbt_path is None else qbt_path
        if qbt_path:
            self.set_save_path(qbt_path, key="qBt-savePath", target_os=target_os, save_file=False, create_backup=False)
        if self.mapped_files is not None and target_os is not None:
            self.logger.debug("Converting Slashes for mapped_files...")
            self._data["mapped_files"] = [convert_slashes(path, target_os) for path in self.mapped_files]
        if save_file:
            self.save()

    def save(self, file_name: Optional[str] = None):
        if file_name is None:
            file_name = self.file_path
<<<<<<< HEAD
        self.logger.info(f'Saving File {file_name}...')
        bencode.write(self._data, file_name)

    def replace_paths(self, existing_path: str, new_path: str, target_os: Optional[str] = None,
                      save_file: bool = True, create_backup: bool = True):
        self.logger.info(f'Replacing Paths in FastResume {self.file_path}...')
        new_save_path = self.save_path.replace(existing_path, new_path)
        self.logger.debug(f'Existing Save Path: {existing_path}, New Save Path: {new_path}, '
                          f'Replaced Save Path: {new_save_path}')
        self.set_save_paths(path=str(new_save_path), target_os=target_os,
                            save_file=save_file, create_backup=create_backup)
        self.logger.info(f'FastResume ({self.file_path}) Paths Replaced!')
=======
        self.logger.info(f"Saving File {file_name}...")
        bencode.write(self._data, file_name)

    def replace_paths(
        self,
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: Optional[str] = None,
        save_file: bool = True,
        create_backup: bool = True,
    ):
        self.logger.info(f"Replacing Paths in FastResume {self.file_path}...")
        if regex_path:
            new_save_path = None
            new_qbt_save_path = None
            pattern = re.compile(existing_path)
            if self.save_path:
                new_save_path = pattern.sub(new_path, self.save_path)
            if self.qbt_save_path:
                new_qbt_save_path = pattern.sub(new_path, self.qbt_save_path)
                if not self.save_path:
                    new_save_path = new_qbt_save_path
            if self.mapped_files:
                self._data["mapped_files"] = [pattern.sub(new_path, path) for path in self.mapped_files]
        else:
            new_save_path = self.save_path.replace(existing_path, new_path) if self.save_path is not None else None
            new_qbt_save_path = (
                self.qbt_save_path.replace(existing_path, new_path) if self.qbt_save_path is not None else None
            )
            if not self.save_path:
                new_save_path = new_qbt_save_path
            if self.mapped_files:
                self._data["mapped_files"] = [path.replace(existing_path, new_path) for path in self.mapped_files]
        self.logger.debug(
            f"Existing Save Path: {existing_path}, New Save Path: {new_path}, " f"Replaced Save Path: {new_save_path}"
        )
        self.set_save_paths(
            path=str(new_save_path),
            qbt_path=new_qbt_save_path,
            target_os=target_os,
            save_file=save_file,
            create_backup=create_backup,
        )
        self.logger.info(f"FastResume ({self.file_path}) Paths Replaced!")
>>>>>>> a5d8dda556d41c60aef1e73ac11a4ee03b13fb21
