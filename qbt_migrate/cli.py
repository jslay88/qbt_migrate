import argparse
import logging
import sys
from pathlib import Path

from qbt_migrate import QBTBatchMove, __version__, discover_bt_backup_path
from qbt_migrate.enums import TargetOS


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


def main():  # noqa: C901
    args = parse_args(sys.argv[1:])
    fmt = (
        "%(message)s"
        if args.log_level == "INFO"
        else "%(asctime)s :: %(levelname)s :: "
        "%(name)s.%(funcName)s: %(message)s"
    )
    logging.basicConfig(format=fmt)
    logger.setLevel(args.log_level)
    logging.getLogger("qbt_migrate").setLevel(args.log_level)
    logging.getLogger("qbt_migrate").propagate = True
    if args.version:
        logger.debug("Version Print requested.")
        logger.info(f"{__version__}")
        logger.debug("Exiting")
        return
    qbm = QBTBatchMove()
    if args.bt_backup_path is not None:
        qbm.bt_backup_path = Path(args.bt_backup_path.strip())
    else:
        bt_backup_path = input(f"BT_backup Path {qbm.bt_backup_path}: ")
        if bt_backup_path.strip():
            qbm.bt_backup_path = Path(bt_backup_path.strip())
    if args.existing_path is None:
        args.existing_path = input("Existing Path: ")
    if args.new_path is None:
        args.new_path = input("New Path: ")

    # Get Valid Regex Input
    if args.regex is None:
        while (
            answer := input(
                "Existing and New paths are regex patterns "
                "(capture groups recommended)? [y/N]: "
            )
            .lower()
            .strip()
        ) not in (
            "y",
            "yes",
            "n",
            "no",
            "",
        ):
            print("Please answer y, n, yes, or no")
        args.regex = answer.lower().strip() in ["y", "yes"]

    # Get Valid Target OS Input
    if args.target_os is None:
        while (
            answer := input(
                "Target OS (Windows, Linux, Mac, Blank for auto-detect): "
            )
            .lower()
            .strip()
        ) not in (
            "windows",
            "linux",
            "mac",
            "",
        ):
            print("Please answer Windows, Linux, or Mac")
        args.target_os = answer.lower().strip()
    if args.target_os:
        args.target_os = (
            TargetOS.WINDOWS
            if args.target_os.lower() in TargetOS.WINDOWS.value
            else TargetOS.POSIX
        )

    # Handle Target OS Auto-Detect if not specified
    if not args.target_os:
        if "/" in args.existing_path and "\\" in args.new_path:
            logger.info(
                "Auto detected target OS change. "
                "Will convert slashes to Windows."
            )
            args.target_os = TargetOS.WINDOWS
        elif "\\" in args.existing_path and "/" in args.new_path:
            logger.info(
                "Auto detected target OS change. "
                "Will convert slashes to Linux/Mac."
            )
            args.target_os = TargetOS.POSIX
        else:
            args.target_os = None

    logger.debug(
        f"Existing Path: {args.existing_path}, New Path: {args.new_path}, "
        f"Target OS: {args.target_os}, Skip Bad Files: {args.skip_bad_files}"
    )
    qbm.run(
        args.existing_path,
        args.new_path,
        args.regex,
        args.target_os,
        True,
        args.skip_bad_files,
    )


if __name__ == "__main__":
    main()  # pragma: no cover
