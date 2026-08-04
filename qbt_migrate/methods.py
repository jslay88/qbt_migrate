import logging
import os
import sys
import zipfile
from pathlib import Path

from qbt_migrate.enums import TargetOS


logger = logging.getLogger(__name__)


def backup_folder(
    folder_path: str | Path,
    archive_path: str | Path,
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


def separator_variants(path: str) -> list[str]:
    """`path` written with each separator convention, original first.

    qBittorrent stores `save_path` and the `qBt-*` keys using the separators of
    whatever platform wrote the file, which is not necessarily the platform
    running this tool. Users, meanwhile, type the pattern with whichever
    separator is in front of them. Matching against every convention makes the
    result independent of both.
    """
    variants = [path]
    for target_os in (TargetOS.POSIX, TargetOS.WINDOWS):
        converted = convert_slashes(path, target_os)
        if converted not in variants:
            variants.append(converted)
    return variants


def matches_path(value: str, existing_path: str) -> bool:
    """Is `existing_path` present in `value` under any separator convention?"""
    return any(
        variant in value for variant in separator_variants(existing_path)
    )


def replace_path(value: str, existing_path: str, new_path: str) -> str:
    """Replace `existing_path` with `new_path` in `value`.

    Matches `existing_path` under any separator convention but substitutes
    `new_path` exactly as given. Mixed separators in the untouched remainder
    are normalized later by `convert_slashes`, once, if a target OS is set.
    """
    for variant in separator_variants(existing_path):
        if variant in value:
            return value.replace(variant, new_path)
    return value


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
