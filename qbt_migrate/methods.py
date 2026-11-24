import contextlib
import logging
import os
import secrets
import stat
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


def atomic_write(path: str | Path, data: bytes) -> None:
    """Replace `path` with `data` so it is never left half-written.

    The bytes go to a temporary file in the same directory, which is synced
    and then renamed over `path`. A failure at any point (an exception, a full
    disk, Ctrl-C) leaves the old file as it was and removes the temporary one.
    An existing file keeps its permission bits and, where the OS allows it
    (e.g. running as root), its owner and group, as an in-place write would.
    """
    # Write through a symlink to its target, as open() would, instead of
    # replacing the link itself with a regular file.
    path = Path(os.path.realpath(path))
    # Same directory, so os.replace is a rename on one filesystem (atomic)
    # and not a copy. The leading dot and .tmp suffix keep it out of the
    # *.fastresume discovery and the zip backup if a crash strands it.
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    # O_EXCL: never reuse or follow something already at the temp name.
    # O_BINARY: Windows would otherwise translate newlines in the data.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    # 0o666 minus the umask is what open(path, "wb") gave a new file.
    fd = os.open(tmp, flags, 0o666)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            # Without this, a power cut right after the rename can leave the
            # new name pointing at blocks that were never written.
            os.fsync(f.fileno())
        _copy_mode_and_owner(path, tmp)
        # Unlike os.rename, os.replace also overwrites an existing file on
        # Windows.
        os.replace(tmp, path)
    # BaseException, so Ctrl-C (KeyboardInterrupt) also removes the temp file.
    except BaseException:
        # Windows refuses to delete a read-only file, and the temp file may
        # already carry a read-only original's mode when os.replace fails.
        with contextlib.suppress(OSError):
            os.chmod(tmp, stat.S_IWRITE)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _copy_mode_and_owner(source: Path, dest: Path) -> None:
    """Give `dest` the permission bits and, if allowed, the owner of `source`.

    The temp file is owned by whoever runs the tool. In Docker that is often
    root while qBittorrent runs as a service user's uid:gid, which could then
    no longer rewrite its own resume file.
    """
    try:
        st = os.stat(source)
    except FileNotFoundError:
        return  # New file: keep the umask-based mode, like open() would.
    os.chmod(dest, stat.S_IMODE(st.st_mode))
    dest_st = os.stat(dest)
    # The common case, and always on Windows (st_uid/st_gid are 0 there and
    # os.chown does not exist).
    if (st.st_uid, st.st_gid) == (dest_st.st_uid, dest_st.st_gid):
        return
    _keep_owner(source, dest, st.st_uid, st.st_gid)


# Set by the first ownership warning, so a run over thousands of files that
# all hit it prints one warning rather than one per file.
_owner_warned = False


def _keep_owner(source: Path, dest: Path, uid: int, gid: int) -> None:
    try:
        os.chown(dest, uid, gid)
        return
    except OSError as e:
        error = e
    try:
        # Only root may give a file away, but a member of the group may still
        # set it (-1 keeps the owner). Group write access is usually how the
        # qBittorrent user can rewrite the file.
        os.chown(dest, -1, gid)
    except OSError:
        # Still save: a file with the wrong owner beats an unmigrated one.
        _warn_owner(
            f"Could not keep the owner of {source} ({uid}:{gid})", error
        )
        return
    logger.debug(f"Kept the group of {source}, not its owner {uid}: {error}")


def _warn_owner(message: str, error: OSError) -> None:
    global _owner_warned
    if _owner_warned:
        logger.debug(f"{message}: {error}")
        return
    _owner_warned = True
    logger.warning(
        f"{message}: {error}. Saved files are owned by the user running "
        "qbt_migrate instead. Further files are only logged at DEBUG level."
    )


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
