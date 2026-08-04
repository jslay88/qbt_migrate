import argparse
import logging
import sys
from pathlib import Path

from bencodepy.exceptions import BencodeDecodeError

from qbt_migrate import QBTBatchMove, __version__, discover_bt_backup_path
from qbt_migrate.enums import TargetOS
from qbt_migrate.exceptions import FastResumeUpdateError


logger = logging.getLogger(__name__)


def parse_args(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-e", "--existing-path", help="Existing root of path to look for."
    )
    parser.add_argument(
        "-n",
        "--new-path",
        help="New root path to replace existing root path with.",
    )
    parser.add_argument(
        "-r",
        "--regex",
        help="Existing and New paths are regex patterns. "
        "(Capture groups recommended).",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "-t",
        "--target-os",
        help="Target OS (converts slashes). "
        "Default will auto-detect if conversion is needed "
        "based on existing vs new.",
        choices=["Windows", "Linux", "Mac"],
    )
    parser.add_argument(
        "-b",
        "--bt-backup-path",
        help="BT_backup Path Override. "
        f"Default is {discover_bt_backup_path()}",
    )
    parser.add_argument(
        "-s",
        "--skip-bad-files",
        help="Skips bad .fastresume files instead of exiting. "
        "Default behavior is to exit.",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "-z",
        "--skip-backup",
        help="Skips creating a backup zip archive of the BT_backup folder. "
        "Default behavior is to create a backup.",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "-l",
        "--log-level",
        help="Log Level, Default is INFO.",
        choices=["DEBUG", "INFO"],
        default="INFO",
    )

    parser.add_argument(
        "-v",
        "--version",
        help=f"Prints the current version number and exits. "
        f"Current qbt_migrate version: {__version__}",
        action="store_true",
        default=False,
    )

    return parser.parse_args(args)


INTERACTIVE_ONLY_HINT = (
    "Nothing is attached to stdin, so there is nobody to prompt. "
    "Pass the missing arguments on the command line, or run the container "
    "with `-it` if you want the prompts."
)


def is_interactive() -> bool:
    """Is there a human on the other end of stdin?

    Prompting unconditionally is why `docker run` without `-it` died with
    `EOFError: EOF when reading a line` (#69), and why a fully flagged
    invocation still blocked: `--regex` and `--target-os` were prompted for
    even when everything else was supplied.
    """
    return sys.stdin is not None and sys.stdin.isatty()


def prompt(message: str) -> str | None:
    """Ask for a value. `None` when running non-interactively."""
    if not is_interactive():
        return None
    return input(message).strip()


def prompt_until(
    message: str, valid: tuple[str, ...], retry: str
) -> str | None:
    """Ask until the answer is one of `valid`. `None` when non-interactive."""
    if not is_interactive():
        return None
    while (answer := input(message).lower().strip()) not in valid:
        print(retry)
    return answer


def configure_logging(log_level: str) -> None:
    fmt = (
        "%(message)s"
        if log_level == "INFO"
        else "%(asctime)s :: %(levelname)s :: "
        "%(name)s.%(funcName)s: %(message)s"
    )
    logging.basicConfig(format=fmt)
    logger.setLevel(log_level)
    logging.getLogger("qbt_migrate").setLevel(log_level)
    logging.getLogger("qbt_migrate").propagate = True


def resolve_bt_backup_path(bt_backup_path: str | None, default: Path) -> Path:
    if bt_backup_path is not None:
        return Path(bt_backup_path.strip())
    answer = prompt(f"BT_backup Path {default}: ")
    return Path(answer) if answer else default


def resolve_regex(regex: bool | None) -> bool:
    if regex is not None:
        return regex
    answer = prompt_until(
        "Existing and New paths are regex patterns "
        "(capture groups recommended)? [y/N]: ",
        ("y", "yes", "n", "no", ""),
        "Please answer y, n, yes, or no",
    )
    return answer in ("y", "yes")


def resolve_target_os(
    target_os: str | None, existing_path: str, new_path: str
) -> TargetOS | None:
    if target_os is None:
        target_os = prompt_until(
            "Target OS (Windows, Linux, Mac, Blank for auto-detect): ",
            ("windows", "linux", "mac", ""),
            "Please answer Windows, Linux, or Mac",
        )
    if target_os:
        return (
            TargetOS.WINDOWS
            if target_os.lower() in TargetOS.WINDOWS.value
            else TargetOS.POSIX
        )
    # Blank, or nobody to ask. Infer from the separators in use.
    if "/" in existing_path and "\\" in new_path:
        logger.info(
            "Auto detected target OS change. Will convert slashes to Windows."
        )
        return TargetOS.WINDOWS
    if "\\" in existing_path and "/" in new_path:
        logger.info(
            "Auto detected target OS change. "
            "Will convert slashes to Linux/Mac."
        )
        return TargetOS.POSIX
    return None


def main() -> int | None:
    args = parse_args(sys.argv[1:])
    configure_logging(args.log_level)
    if args.version:
        logger.debug("Version Print requested.")
        logger.info(f"{__version__}")
        logger.debug("Exiting")
        return None

    qbm = QBTBatchMove()
    qbm.bt_backup_path = resolve_bt_backup_path(
        args.bt_backup_path, qbm.bt_backup_path
    )
    if args.existing_path is None:
        args.existing_path = prompt("Existing Path: ")
    if args.new_path is None:
        args.new_path = prompt("New Path: ")
    for name, value in (
        ("--existing-path/-e", args.existing_path),
        ("--new-path/-n", args.new_path),
    ):
        if not value:
            logger.error(f"❌ {name} is required. {INTERACTIVE_ONLY_HINT}")
            return 2

    args.regex = resolve_regex(args.regex)
    args.target_os = resolve_target_os(
        args.target_os, args.existing_path, args.new_path
    )

    logger.debug(
        f"Existing Path: {args.existing_path}, New Path: {args.new_path}, "
        f"Target OS: {args.target_os}, Skip Bad Files: {args.skip_bad_files}, "
        f"Skip Backup: {args.skip_backup}"
    )
    if args.skip_backup:
        logger.warning(
            "⚠️ Skipping the backup archive. Make sure you have one already."
        )
    try:
        qbm.run(
            args.existing_path,
            args.new_path,
            args.regex,
            args.target_os,
            not args.skip_backup,
            args.skip_bad_files,
        )
    except (BencodeDecodeError, ValueError) as e:
        logger.error(
            f"❌ Could not read a .fastresume file: {e}\n"
            f"Nothing was changed. Re-run with -s/--skip-bad-files to skip "
            f"unreadable files and migrate the rest."
        )
        return 1
    except NotADirectoryError as e:
        logger.error(
            f"❌ BT_backup path is not a directory: {e}\n"
            f"Point -b/--bt-backup-path at your qBittorrent BT_backup folder."
        )
        return 2
    except FastResumeUpdateError as e:
        logger.error(
            f"❌ {len(e.failures)} file(s) were not updated. "
            f"qBittorrent will still have the old paths for them. "
            f"Restore from the backup archive in the BT_backup directory "
            f"if you need to start over."
        )
        return 1
    return None


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
