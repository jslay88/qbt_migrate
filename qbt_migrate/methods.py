import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Union

from qbt_migrate.enums import TargetOS


logger = logging.getLogger(__name__)


def backup_folder(
    folder_path: Union[str, Path],
    archive_path: Union[str, Path],
    include_torrents: bool = True,
):
    logger.info(f"🗄️ Creating Archive {archive_path} ...")
    folder_path = Path(folder_path)
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for file in folder_path.iterdir():
            if file.name.endswith(".fastresume") or (
                include_torrents and file.name.endswith(".torrent")
            ):
                logger.debug(f"Archiving {file} into {archive_path}...")
                archive.write(file)
    logger.info("✔️ Done!")


def convert_slashes(path: str, target_os: TargetOS):
    if not isinstance(target_os, TargetOS):
        raise ValueError(
            f"Target OS is not valid. Must be enum TargetOs. "
            f"Received: {type(target_os)}"
        )
    if target_os is TargetOS.WINDOWS:
        logger.debug("Convert to Windows Slashes")
        return path.replace("/", "\\")
    logger.debug("Convert to Unix Slashes")
    return path.replace("\\", "/")


def discover_bt_backup_path():
    logger.debug("Discovering BT_backup path...")
    if sys.platform.startswith("win32"):
        logger.debug("Windows System")
        return Path(os.getenv("localappdata"), "qBittorrent\\BT_backup")

    if (
        Path("/.dockerenv").is_file()
        and Path("/config/qBittorrent/BT_backup").is_dir()
    ):
        # Default path for config under for image:
        # https://docs.linuxserver.io/images/docker-qbittorrent
        logger.debug("qBittorrent Docker container detected")
        return Path("/config/qBittorrent/BT_backup")

    logger.debug("Linux/Mac System")
    return Path(os.getenv("HOME"), ".local/share/data/qBittorrent/BT_backup")
