import argparse
import logging
import sys
from pathlib import Path

from bencodepy.exceptions import BencodeDecodeError

from qbt_migrate import QBTBatchMove, __version__, discover_bt_backup_path
from qbt_migrate.enums import TargetOS
from qbt_migrate.exceptions import FastResumeUpdateError
from qbt_migrate.methods import matches_path
from qbt_migrate.plans import MigrationPlan, PlanSummary
from qbt_migrate.process import find_processes, stop_processes


logger = logging.getLogger(__name__)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
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
        "-m",
        "--map",
        help="Replace EXISTING with NEW. Repeatable, for several roots in "
        "one run. Each path uses the first mapping that matches it, once, "
        "so mappings never chain: put narrower roots first. -e/-n, if "
        "given, is tried first.",
        action="append",
        nargs=2,
        metavar=("EXISTING", "NEW"),
        dest="mappings",
        default=None,
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
        "based on existing vs new, over every mapping.",
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
        "-k",
        "--stop-qbittorrent",
        help="Stop a running qBittorrent without asking first, and wait "
        "for it to exit.",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--ignore-running",
        help="Run even if qBittorrent is still running. Unsafe: it will "
        "overwrite your changes from memory when it exits.",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "-d",
        "--dry-run",
        help="Show what would change and exit without writing anything.",
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


BAD_FILE_HINT = (
    "❌ Could not read a .fastresume file: {error}\n"
    "Nothing was changed. Re-run with -s/--skip-bad-files to skip unreadable "
    "files and migrate the rest."
)

BAD_BACKUP_PATH_HINT = (
    "❌ BT_backup path is not a directory: {error}\n"
    "Point -b/--bt-backup-path at your qBittorrent BT_backup folder."
)

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


# Beyond this many files a full listing is unreadable, and libraries of tens of
# thousands of torrents are the normal case for this tool.
DRY_RUN_DETAIL_LIMIT = 20


def quoted(value: str) -> str:
    """Wrap a path in quotes so leading and trailing separators are visible.

    Deliberately not `repr`, which escapes backslashes and would render
    `S:\\Pictures\\` as `S:\\\\Pictures\\\\`. Separator confusion is already
    this tool's most common support question without inventing more of it.
    """
    return f"'{value}'"


def log_plan(plan: MigrationPlan) -> None:
    """Log one file's changes, values quoted so separators are visible."""
    logger.info(f"{plan.name or plan.file_path.name}")
    if plan.error is not None:
        logger.info(f"    would fail: {plan.error}")
        return
    for change in plan.changes:
        arrow = f"{quoted(change.old)} -> {quoted(change.new)}"
        if change.mappings:
            numbers = ", ".join(str(index + 1) for index in change.mappings)
            plural = "s" if len(change.mappings) > 1 else ""
            arrow += f"  (mapping{plural} {numbers})"
        if change.is_list:
            logger.info(
                f"    {change.key:16}  {change.changed_entries} of "
                f"{change.total_entries} entries, e.g. {arrow}"
            )
        else:
            logger.info(f"    {change.key:16}  {arrow}")


def log_plan_summary(summary: PlanSummary, verbose: bool) -> None:
    changing = summary.changing
    shown = changing if verbose else changing[:DRY_RUN_DETAIL_LIMIT]
    for plan in shown:
        log_plan(plan)
    if len(changing) > len(shown):
        logger.info(
            f"... and {len(changing) - len(shown)} more. "
            f"Re-run with -l DEBUG to list every file."
        )

    for plan in summary.failing:
        log_plan(plan)

    unchanged = summary.discovered - len(changing) - len(summary.failing)
    logger.info(
        f"{'🔍' if changing else '⚠️'} "
        f"{len(changing)} of {summary.discovered} relevant fastresume "
        f"file{'' if summary.discovered == 1 else 's'} would be updated"
        f"{f', {unchanged} already match' if unchanged else ''}"
        f"{f', {len(summary.failing)} would fail' if summary.failing else ''}."
        f" Nothing was written."
    )


def preflight_qbittorrent(args: argparse.Namespace) -> int | None:
    """Refuse to write while qBittorrent is running, and offer to stop it.

    Returns an exit code to bail out with, or None to carry on. Editing
    `.fastresume` files underneath a running client accomplishes nothing: it
    rewrites them from memory on exit. Detection is best effort, and finds
    nothing from inside a container, so this is a safety net rather than a
    guarantee.
    """
    if args.ignore_running:
        logger.warning(
            "⚠️ Not checking whether qBittorrent is running. If it is, it will "
            "overwrite these changes from memory when it exits."
        )
        return None

    running = find_processes()
    if not running:
        logger.debug("No running qBittorrent found.")
        return None

    listed = ", ".join(str(process) for process in running)
    logger.warning(f"⚠️ qBittorrent is running: {listed}")

    if not args.stop_qbittorrent:
        if not is_interactive():
            logger.error(
                "❌ Refusing to run while qBittorrent is running. It would "
                "overwrite these changes from memory when it exits.\n"
                "Pass -k/--stop-qbittorrent to stop it first, or "
                "--ignore-running to override."
            )
            return 2
        answer = prompt_until(
            "Stop it now and wait for it to exit? [Y/n]: ",
            ("y", "yes", "n", "no", ""),
            "Please answer y, n, yes, or no",
        )
        if answer in ("n", "no"):
            logger.error(
                "❌ Nothing was changed. Close qBittorrent and run again."
            )
            return 2

    still_running = stop_processes(running)
    if still_running:
        listed = ", ".join(str(process) for process in still_running)
        logger.error(
            f"❌ qBittorrent did not exit: {listed}\n"
            f"Nothing was changed. Quit it manually through File -> Exit, "
            f"wait for the window to disappear, then run again."
        )
        return 2
    return None


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


def detect_target_os(existing_path: str, new_path: str) -> TargetOS | None:
    """Infer a target OS from the separators one mapping uses."""
    if "/" in existing_path and "\\" in new_path:
        return TargetOS.WINDOWS
    if "\\" in existing_path and "/" in new_path:
        return TargetOS.POSIX
    return None


def resolve_target_os(
    target_os: str | None,
    existing_path: str,
    new_path: str,
    extra_mappings: list[tuple[str, str]] | None = None,
) -> TargetOS | None:
    """The target OS from -t, the prompt, or the separators in use.

    :raises ValueError: If auto-detecting and the mappings disagree.
    """
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
    mappings = [(existing_path, new_path), *(extra_mappings or [])]
    detected = {
        found
        for found in (detect_target_os(e, n) for e, n in mappings)
        if found is not None
    }
    if len(detected) > 1:
        raise ValueError(
            "The mappings disagree on the target OS: some go to Windows, "
            "some to Linux/Mac. Pass -t/--target-os to choose one."
        )
    if TargetOS.WINDOWS in detected:
        logger.info(
            "Auto detected target OS change. Will convert slashes to Windows."
        )
        return TargetOS.WINDOWS
    if TargetOS.POSIX in detected:
        logger.info(
            "Auto detected target OS change. "
            "Will convert slashes to Linux/Mac."
        )
        return TargetOS.POSIX
    return None


def resolve_mappings(args: argparse.Namespace) -> str | None:
    """Fold -m/--map into -e/-n plus `args.extra_mappings`.

    The first mapping always lives in -e/-n, so the single-pair code path is
    the one every run takes. Returns an error message, or None.
    """
    args.extra_mappings = [
        (existing, new) for existing, new in args.mappings or []
    ]
    if not args.extra_mappings:
        return None
    if (args.existing_path is None) != (args.new_path is None):
        return (
            "-e/--existing-path and -n/--new-path go together. With "
            "-m/--map, give both or neither."
        )
    # From Python 3.12 argparse accepts an option-like word as a value of an
    # nargs=2 option, so a forgotten NEW silently swallows the next flag:
    # `-m /data/movies -d` maps to '-d' and writes instead of dry-running.
    # 3.10 and 3.11 reject it themselves; -e/-n do on every version.
    for value in (v for pair in args.extra_mappings for v in pair):
        if value.startswith("-"):
            return (
                f"-m/--map takes EXISTING NEW, and {quoted(value)} looks "
                f"like an option. Did you leave out NEW? Paths given to "
                f"-m cannot start with '-'."
            )
    # An empty EXISTING is a substring of every path and would match them all.
    if any(not existing or not new for existing, new in args.extra_mappings):
        return "-m/--map needs a non-empty EXISTING and NEW."
    if args.existing_path is None:
        args.existing_path, args.new_path = args.extra_mappings.pop(0)
    return None


def unreachable_mapping(
    mappings: list[tuple[str, str]], regex_path: bool
) -> str | None:
    """Explain a mapping that can never apply, or None.

    Any path containing a later EXISTING that contains an earlier one is
    claimed by the earlier mapping first, so the later one is dead and its
    torrents land under the wrong NEW. That is never what was meant, so it
    stops the run rather than warns. Regex patterns are not compared.
    """
    if regex_path:
        return None
    for later, (existing, _) in enumerate(mappings):
        for earlier in range(later):
            if matches_path(existing, mappings[earlier][0]):
                return (
                    f"Mapping {later + 1} {quoted(existing)} can never "
                    f"match: mapping {earlier + 1} "
                    f"{quoted(mappings[earlier][0])} takes every path it "
                    f"would. Put the narrower root first (-e/-n is always "
                    f"first)."
                )
    return None


def resolve_mapping_options(args: argparse.Namespace) -> str | None:
    """Settle the target OS and check the mappings. An error, or None."""
    mappings = [(args.existing_path, args.new_path), *args.extra_mappings]
    unreachable = unreachable_mapping(mappings, args.regex)
    if unreachable is not None:
        return unreachable
    try:
        args.target_os = resolve_target_os(
            args.target_os,
            args.existing_path,
            args.new_path,
            args.extra_mappings,
        )
    except ValueError as e:
        return str(e)
    return None


def log_mappings(args: argparse.Namespace) -> None:
    """Number the mappings, so dry run lines can refer back to them."""
    if not args.extra_mappings:
        return
    logger.info("Mappings, first match wins:")
    mappings = [(args.existing_path, args.new_path), *args.extra_mappings]
    for number, (existing, new) in enumerate(mappings, start=1):
        logger.info(f"    {number}: {quoted(existing)} -> {quoted(new)}")


def preview_migration(
    qbm: QBTBatchMove, args: argparse.Namespace
) -> int | None:
    try:
        summary = qbm.plan(
            args.existing_path,
            args.new_path,
            args.regex,
            args.target_os,
            args.skip_bad_files,
            args.extra_mappings,
        )
    except (BencodeDecodeError, ValueError) as e:
        logger.error(BAD_FILE_HINT.format(error=e))
        return 1
    except NotADirectoryError as e:
        logger.error(BAD_BACKUP_PATH_HINT.format(error=e))
        return 2
    log_plan_summary(summary, verbose=args.log_level == "DEBUG")
    return None


def apply_migration(qbm: QBTBatchMove, args: argparse.Namespace) -> int | None:
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
            extra_mappings=args.extra_mappings,
        )
    except (BencodeDecodeError, ValueError) as e:
        logger.error(BAD_FILE_HINT.format(error=e))
        return 1
    except NotADirectoryError as e:
        logger.error(BAD_BACKUP_PATH_HINT.format(error=e))
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


def main() -> int | None:
    args = parse_args(sys.argv[1:])
    configure_logging(args.log_level)
    if args.version:
        logger.debug("Version Print requested.")
        logger.info(f"{__version__}")
        logger.debug("Exiting")
        return None

    mapping_error = resolve_mappings(args)
    if mapping_error is not None:
        logger.error(f"❌ {mapping_error}")
        return 2

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
    option_error = resolve_mapping_options(args)
    if option_error is not None:
        logger.error(f"❌ {option_error}")
        return 2

    logger.debug(
        f"Existing Path: {args.existing_path}, New Path: {args.new_path}, "
        f"Target OS: {args.target_os}, Skip Bad Files: {args.skip_bad_files}, "
        f"Skip Backup: {args.skip_backup}, Dry Run: {args.dry_run}, "
        f"Extra Mappings: {args.extra_mappings}"
    )
    log_mappings(args)
    # A dry run writes nothing, so it is safe with qBittorrent open and is the
    # obvious thing to reach for while deciding on a pattern.
    if args.dry_run:
        return preview_migration(qbm, args)

    bail = preflight_qbittorrent(args)
    if bail is not None:
        return bail
    return apply_migration(qbm, args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
