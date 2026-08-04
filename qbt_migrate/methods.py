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
) -> None:
    logger.info(f"🗄️ Creating Archive {archive_path} ...")
    folder_path = Path(folder_path)
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for file in sorted(folder_path.iterdir()):
            if file.name.endswith(".fastresume") or (
                include_torrents and file.name.endswith(".torrent")
            ):
                logger.debug(f"Archiving {file} into {archive_path}...")
                # Flat entries. Without an arcname, zipfile stores the whole
                # source path minus the leading separator, so restoring meant
                # digging the files out of a nested directory tree that
                # mirrored the machine the backup was taken on.
                archive.write(file, arcname=file.name)
    logger.info("✔️ Done!")


def convert_slashes(path: str, target_os: TargetOS) -> str:
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


def bt_backup_path_candidates() -> list[Path]:
    """Every location qBittorrent might keep BT_backup, in preference order.

    Mirrors `Private::DefaultProfile::dataLocation` in qBittorrent's
    src/base/profile_p.cpp, which resolves through Qt's QStandardPaths:

    * Windows and macOS use `AppLocalDataLocation`
    * everything else uses `GenericDataLocation`, falling back to the legacy
      `<data>/data/qBittorrent` directory only when the current one is absent
      and the legacy one exists
    """
    if sys.platform.startswith("win32"):
        logger.debug("Windows System")
        # Path(os.getenv(...), ...) raised TypeError when the variable was
        # unset, which is easy to hit under service accounts and bare shells.
        local_app_data = os.getenv("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        return [base / "qBittorrent" / "BT_backup"]

    if sys.platform.startswith("darwin"):
        logger.debug("macOS System")
        # Was handed the Linux path, which is never correct on macOS.
        return [
            Path.home()
            / "Library"
            / "Application Support"
            / "qBittorrent"
            / "BT_backup"
        ]

    logger.debug("Linux System")
    # Default path for config under for image:
    # https://docs.linuxserver.io/images/docker-qbittorrent
    docker = Path("/config/qBittorrent/BT_backup")
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    data_home = (
        Path(xdg_data_home)
        if xdg_data_home
        else Path.home() / ".local" / "share"
    )
    return [
        *([docker] if Path("/.dockerenv").is_file() else []),
        data_home / "qBittorrent" / "BT_backup",
        # Pre-4.x layout. qBittorrent still reads it when it is the only one
        # present, so it stays in the list, just no longer first.
        data_home / "data" / "qBittorrent" / "BT_backup",
    ]


def discover_bt_backup_path() -> Path:
    """First BT_backup candidate that exists, else the preferred candidate."""
    logger.debug("Discovering BT_backup path...")
    candidates = bt_backup_path_candidates()
    for candidate in candidates:
        if candidate.is_dir():
            logger.debug(f"Found BT_backup at {candidate}")
            return candidate
    logger.debug(
        f"No BT_backup directory found, falling back to {candidates[0]}. "
        f"Checked: {', '.join(str(path) for path in candidates)}"
    )
    return candidates[0]
