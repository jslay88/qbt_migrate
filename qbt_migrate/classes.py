import logging
import re
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import copy, deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import bencodepy
from bencodepy.exceptions import BencodeDecodeError

from qbt_migrate.enums import TargetOS
from qbt_migrate.exceptions import FastResumeUpdateError
from qbt_migrate.methods import (
    backup_folder,
    convert_slashes,
    discover_bt_backup_path,
    matches_path,
    replace_path,
)
from qbt_migrate.plans import MigrationPlan, PlanSummary, diff_data


logger = logging.getLogger(__name__)
bencode = bencodepy.Bencode(encoding="utf-8", encoding_fallback="all")


class QBTBatchMove:
    logger = logging.getLogger(__name__ + ".QBTBatchMove")

    def __init__(self, bt_backup_path: str | Path | None = None):
        if bt_backup_path is None:
            bt_backup_path = discover_bt_backup_path()
        self.logger.debug(f"BT_backup Path: {bt_backup_path}")
        self.bt_backup_path = Path(bt_backup_path)
        self.discovered_files: set[FastResume] = set()

    def run(
        self,
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: TargetOS | None = None,
        create_backup: bool = True,
        skip_bad_files: bool = False,
        max_workers: int | None = None,
    ) -> None:
        """
        Perform Batch Processing of path changes.
        :param existing_path: Existing path to look for
        :type existing_path: str
        :param new_path: New Path to replace with
        :type new_path: str
        :param regex_path: Existing and New Paths are regex
        patterns with capture groups
        :type regex_path: bool
        :param target_os: If targeting a different OS than the source.
        :type target_os: TargetOS
        :param create_backup: Create a backup archive of the
        BT_backup directory?
        :type create_backup: bool
        :param skip_bad_files: Skip .fastresume files that
        cannot be read successfully.
        :type skip_bad_files: bool
        :param max_workers: Size of the thread pool used to write files.
        Defaults to `ThreadPoolExecutor`'s own default.
        :type max_workers: int
        :raises FastResumeUpdateError: If any discovered file failed to update.
        """
        if not self.bt_backup_path.is_dir():
            raise NotADirectoryError(self.bt_backup_path)
        if create_backup:
            backup_filename = (
                f"fastresume_backup"
                f"{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
            )
            backup_folder(
                self.bt_backup_path, self.bt_backup_path / backup_filename
            )

        self.logger.info(
            f"🕵️ Searching for .fastresume files with path {existing_path} ..."
        )
        failures: dict[Path, BaseException] = {}
        count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures: dict[Future[None], FastResume] = {}
            for fast_resume in self.discover_relevant_fast_resume(
                self.bt_backup_path,
                existing_path,
                regex_path,
                not skip_bad_files,
            ):
                count += 1
                self.discovered_files.add(fast_resume)
                futures[
                    pool.submit(
                        fast_resume.replace_paths,
                        existing_path,
                        new_path,
                        regex_path,
                        target_os,
                        True,
                        False,
                    )
                ] = fast_resume
            for future in as_completed(futures):
                fast_resume = futures[future]
                try:
                    future.result()
                except Exception as e:  # noqa: BLE001
                    self.logger.error(
                        f"🛑 Failed to update {fast_resume.file_path}: {e}"
                    )
                    failures[fast_resume.file_path] = e

        updated = count - len(failures)
        logger.info(
            f"{'✔️' if updated else '⚠️'} "
            f"Updated {updated} of {count} relevant fastresume "
            f"file{'' if count == 1 else 's'}!"
        )
        if failures:
            raise FastResumeUpdateError(failures)

    def plan(
        self,
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: TargetOS | None = None,
        skip_bad_files: bool = False,
    ) -> PlanSummary:
        """Work out what `run` would change, writing nothing.

        Same arguments as `run` minus the ones that only matter when writing,
        so a dry run and the real thing cannot be given different inputs.

        :raises NotADirectoryError: If the BT_backup path is not a directory.
        """
        if not self.bt_backup_path.is_dir():
            raise NotADirectoryError(self.bt_backup_path)

        self.logger.info(
            f"🔍 Dry run. Searching for .fastresume files with path "
            f"{existing_path} ..."
        )
        summary = PlanSummary()
        for fast_resume in self.discover_relevant_fast_resume(
            self.bt_backup_path,
            existing_path,
            regex_path,
            not skip_bad_files,
        ):
            try:
                summary.plans.append(
                    fast_resume.plan_paths(
                        existing_path, new_path, regex_path, target_os
                    )
                )
            except Exception as e:  # noqa: BLE001
                # Surfaced rather than raised: knowing which files would fail
                # is the whole point of asking first.
                self.logger.error(
                    f"🛑 {fast_resume.file_path} would fail to update: {e}"
                )
                summary.plans.append(
                    MigrationPlan(
                        file_path=fast_resume.file_path, error=str(e)
                    )
                )
        return summary

    @classmethod
    def discover_relevant_fast_resume(
        cls,
        bt_backup_path: str | Path,
        existing_path: str,
        regex_path: bool = False,
        raise_on_error: bool = True,
    ) -> Iterator["FastResume"]:
        """
        Find .fastresume files that contain the existing path.
        :param bt_backup_path: Path to BT_backup folder
        :type bt_backup_path: str | Path
        :param existing_path: The existing path to look for
        :type existing_path: str
        :param regex_path: Existing Path is a regex pattern with capture groups
        :type: bool
        :param raise_on_error: Raise if error parsing .fastresume files
        :type raise_on_error: bool
        :return: List of FastResume Objects
        :rtype: list[FastResume]
        """
        bt_backup_path = Path(bt_backup_path)
        # Sorted so processing order (and therefore log output) is reproducible
        # across runs and filesystems.
        for file in sorted(bt_backup_path.iterdir()):
            if file.is_dir():
                continue
            if file.name.endswith(".fastresume"):
                try:
                    fast_resume = FastResume(bt_backup_path / file)
                except (
                    BencodeDecodeError,
                    FileNotFoundError,
                    ValueError,
                ) as e:
                    if raise_on_error:
                        cls.logger.critical(
                            f"🛑 Unable to parse {file}. Stopping Discovery!"
                        )
                        raise e
                    cls.logger.warning(
                        f"⚠️ Unable to parse {file}. Skipping!\n\n{e}"
                    )
                    continue
                if (
                    fast_resume.save_path is not None
                    and matches_path(fast_resume.save_path, existing_path)
                ) or (
                    fast_resume.qbt_save_path is not None
                    and matches_path(fast_resume.qbt_save_path, existing_path)
                ):
                    yield fast_resume
                elif regex_path and (
                    (
                        fast_resume.save_path is not None
                        and re.search(existing_path, fast_resume.save_path)
                    )
                    or (
                        fast_resume.qbt_save_path is not None
                        and re.search(existing_path, fast_resume.qbt_save_path)
                    )
                ):
                    yield fast_resume
                else:
                    logger.debug(
                        f"FastResume {file} is not relevant, "
                        f"Save Path: {fast_resume.save_path}, "
                        f"qBt-savePath: {fast_resume.qbt_save_path}"
                    )
        return

    @classmethod
    def backup_folder(
        cls, folder_path: str | Path, archive_path: str | Path
    ) -> None:
        backup_folder(folder_path, archive_path)

    @classmethod
    def update_fastresume(
        cls,
        fast_resume: "FastResume",
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: TargetOS | None = None,
        save_file: bool = True,
        create_backup: bool = True,
    ) -> None:
        if not isinstance(fast_resume, FastResume):
            raise TypeError("Not a FastResume object, cannot replace paths!")
        fast_resume.replace_paths(
            existing_path,
            new_path,
            regex_path,
            target_os,
            save_file,
            create_backup,
        )


class FastResume:
    logger = logging.getLogger(__name__ + ".FastResume")

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        if not self.file_path.is_file():
            raise FileNotFoundError(self.file_path)
        self.logger.debug(f"Loading Fast Resume: {self.file_path}")
        # Bencode is schemaless, so everything read out of it is Any. The
        # property accessors below are where we assert what we expect.
        self._data: dict[str, Any] = bencode.read(self.file_path)
        self.logger.debug(f"Fast Resume ({self.file_path}) Init Complete.")

    @property
    def file_path(self) -> Path:
        return self._file_path

    @property
    def backup_filename(self) -> Path:
        return Path(
            f"{self.file_path}.{datetime.now().strftime('%Y%m%d%H%M%S')}.bkup"
        )

    @property
    def save_path(self) -> str | None:
        return cast("str | None", self._data.get("save_path"))

    @property
    def qbt_download_path(self) -> str | None:
        return cast("str | None", self._data.get("qBt-downloadPath"))

    @property
    def qbt_save_path(self) -> str | None:
        return cast("str | None", self._data.get("qBt-savePath"))

    @property
    def mapped_files(self) -> list[str] | None:
        return cast("list[str] | None", self._data.get("mapped_files"))

    def set_save_path(
        self,
        path: str,
        key: str = "save_path",
        target_os: TargetOS | None = None,
        save_file: bool = True,
        create_backup: bool = True,
    ) -> None:
        if key not in ["save_path", "qBt-savePath", "qBt-downloadPath"]:
            raise KeyError(
                "When setting a save path, "
                "key must be `save_path` or `qBt-savePath`. "
                f"Received {key}"
            )
        if create_backup:
            self.save(self.backup_filename)
        if target_os is not None:
            path = convert_slashes(path, target_os)
        self.logger.debug(
            f"Setting {key}... Old: {self._data.get(key, None)},"
            f" New: {path}, Target OS: {target_os}"
        )
        self._data[key] = path
        if save_file:
            self.save()

    def set_save_paths(
        self,
        path: str | None,
        qbt_path: str | None = None,
        qbt_download_path: str | None = None,
        target_os: TargetOS | None = None,
        save_file: bool = True,
        create_backup: bool = True,
    ) -> None:
        self.logger.debug(f"Set Save Paths in {self.file_path}...")
        self.logger.debug(f"path: {path}")
        self.logger.debug(f"qbt_path: {qbt_path}")
        self.logger.debug(f"qbt_download_path: {qbt_download_path}")
        self.logger.debug(f"target_os: {target_os}")
        self.logger.debug(f"save_file: {save_file}")
        self.logger.debug(f"create_backup: {create_backup}")
        # Validate before writing the backup, so a rejected call does not leave
        # a stray .bkup behind.
        if path is None or not path.strip():
            raise ValueError(
                f"Cannot set an empty save path on {self.file_path}"
            )
        if create_backup:
            self.save(self.backup_filename)
        self.set_save_path(
            path,
            key="save_path",
            target_os=target_os,
            save_file=False,
            create_backup=False,
        )
        qbt_path = path if qbt_path is None else qbt_path
        if qbt_path:
            self.set_save_path(
                qbt_path,
                key="qBt-savePath",
                target_os=target_os,
                save_file=False,
                create_backup=False,
            )
        if qbt_download_path:
            self.set_save_path(
                qbt_download_path,
                key="qBt-downloadPath",
                target_os=target_os,
                save_file=False,
                create_backup=False,
            )
        elif self.qbt_download_path and target_os is not None:
            # No replacement was computed for this key, but a target OS change
            # still has to normalize its separators. It must never be
            # overwritten with the save path: it is the incomplete-downloads
            # directory and is frequently a deliberately different location.
            self.set_save_path(
                self.qbt_download_path,
                key="qBt-downloadPath",
                target_os=target_os,
                save_file=False,
                create_backup=False,
            )
        if self.mapped_files is not None and target_os is not None:
            self.logger.debug("Converting Slashes for mapped_files...")
            self._data["mapped_files"] = [
                convert_slashes(path, target_os) for path in self.mapped_files
            ]
        if save_file:
            self.save()

    def save(self, file_name: str | Path | None = None) -> None:
        if file_name is None:
            file_name = self.file_path
        self.logger.debug(f"Saving File {file_name}...")
        bencode.write(self._data, file_name)

    def plan_paths(
        self,
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: TargetOS | None = None,
    ) -> MigrationPlan:
        """What `replace_paths` would change here, without changing anything.

        Runs the real replacement against an in-memory copy and diffs the
        result, rather than reimplementing the rules. A preview that predicts
        its own answer can drift from what an apply does, and a preview that
        lies is worse than no preview.

        :raises ValueError: If the resulting save path would be empty, the same
        as `replace_paths` would.
        """
        probe = copy(self)
        probe._data = deepcopy(self._data)
        # save_file and create_backup are both off, so nothing touches disk.
        probe.replace_paths(
            existing_path,
            new_path,
            regex_path,
            target_os,
            save_file=False,
            create_backup=False,
        )
        return diff_data(self.file_path, self._data, probe._data)

    def replace_paths(
        self,
        existing_path: str,
        new_path: str,
        regex_path: bool = False,
        target_os: TargetOS | None = None,
        save_file: bool = True,
        create_backup: bool = True,
    ) -> None:
        self.logger.debug(f"Replacing Paths in FastResume {self.file_path}...")
        self.logger.debug(f"Existing Path: {existing_path}")
        self.logger.debug(f"New Path: {new_path}")
        self.logger.debug(f"Regex Path: {regex_path}")
        self.logger.debug(f"Target OS: {target_os}")
        self.logger.debug(f"Save File: {save_file}")
        self.logger.debug(f"Create Backup: {create_backup}")
        if regex_path:
            new_save_path = None
            new_qbt_save_path = None
            new_qbt_download_path = None
            pattern = re.compile(existing_path)
            if self.save_path:
                new_save_path = pattern.sub(new_path, self.save_path)
            if self.qbt_save_path:
                new_qbt_save_path = pattern.sub(new_path, self.qbt_save_path)
                if not self.save_path:
                    new_save_path = new_qbt_save_path
            if self.qbt_download_path:
                new_qbt_download_path = pattern.sub(
                    new_path, self.qbt_download_path
                )
            if self.mapped_files:
                self._data["mapped_files"] = [
                    pattern.sub(new_path, path) for path in self.mapped_files
                ]
        else:
            # Every key is matched the same way. Assuming a separator
            # convention per key silently skipped the replacement when the
            # fastresume did not happen to use it, leaving the old drive letter
            # in place. See #75.
            new_save_path = (
                replace_path(self.save_path, existing_path, new_path)
                if self.save_path is not None
                else None
            )
            new_qbt_save_path = (
                replace_path(self.qbt_save_path, existing_path, new_path)
                if self.qbt_save_path is not None
                else None
            )
            new_qbt_download_path = (
                replace_path(self.qbt_download_path, existing_path, new_path)
                if self.qbt_download_path is not None
                else None
            )
            if not self.save_path:
                new_save_path = new_qbt_save_path
            if self.mapped_files:
                self._data["mapped_files"] = [
                    replace_path(path, existing_path, new_path)
                    for path in self.mapped_files
                ]
        self.logger.debug(
            f"Existing Save Path: {existing_path}, New Save Path: {new_path}, "
            f"Replaced Save Path: {new_save_path}"
        )
        self.set_save_paths(
            path=new_save_path,
            qbt_path=new_qbt_save_path,
            qbt_download_path=new_qbt_download_path,
            target_os=target_os,
            save_file=save_file,
            create_backup=create_backup,
        )
        self.logger.debug(f"FastResume ({self.file_path}) Paths Replaced!")
