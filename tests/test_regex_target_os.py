"""Target OS auto-detection in regex mode.

A backreference such as `\\1` in the replacement is not a Windows separator.
Counting it as one converted every Linux-to-Linux regex migration run without
`-t` to backslashes.
"""

import pytest

from qbt_migrate.classes import FastResume
from qbt_migrate.cli import main, regex_separators, resolve_target_os
from qbt_migrate.enums import TargetOS


@pytest.mark.parametrize(
    "pattern, expected",
    [
        pytest.param(r"/srv/media/\1", "/srv/media/", id="group"),
        pytest.param(r"/srv/media/\12", "/srv/media/2", id="two"),
        pytest.param(r"/mnt/\g<1>/\g<name>", "/mnt//", id="named"),
        pytest.param(r"^/some/(\w+)/.*$", "^/some/(+)/.*$", id="class"),
        pytest.param(r"X:\\\\(\w+)", "X:\\\\(+)", id="escaped-backslash"),
        pytest.param(r"\/data", "/data", id="escaped-slash"),
        pytest.param("", "", id="empty"),
    ],
)
def test_regex_separators(pattern, expected):
    """Escapes and backreferences go, escaped separators stay."""
    assert regex_separators(pattern) == expected


@pytest.mark.parametrize(
    "existing_path, new_path",
    [
        pytest.param(r"^/data/(.*)", r"/srv/media/\1", id="numbered"),
        pytest.param(r"^/data/(.*)", r"/srv/media/\g<1>", id="g-group"),
        pytest.param(r"^/some/(\w+)/.*$", r"/\1/regex", id="readme"),
    ],
)
def test_backreference_is_not_a_windows_separator(existing_path, new_path):
    """A Linux-to-Linux regex run is not converted to backslashes."""
    assert resolve_target_os("", existing_path, new_path, True) is None


def test_regex_linux_to_windows_still_detected():
    """An escaped backslash in the replacement is a real one."""
    assert (
        resolve_target_os("", r"^/data/(.*)", r"D:\\Data\\\1", True)
        is TargetOS.WINDOWS
    )


def test_regex_windows_to_linux_still_detected():
    """Escaped backslashes in the pattern still mean a Windows source."""
    assert (
        resolve_target_os("", r"X:\\(\w+)", r"/mnt/x/\1", True)
        is TargetOS.POSIX
    )


def test_plain_mode_detection_unchanged():
    """Without `-r` a backslash is taken literally, as before."""
    assert resolve_target_os("", "/data", r"/mnt/data/\1") is TargetOS.WINDOWS


def test_regex_run_without_target_os_keeps_forward_slashes(
    write_fastresume, temp_dir, cli_args
):
    """The non-interactive run from the report, end to end."""
    write_fastresume(
        "a.fastresume",
        {"save_path": "/data/movies/x", "qBt-savePath": "/data/movies/x"},
    )
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        r"^/data/(.*)",
        "-n",
        r"/srv/media/\1",
        "-r",
        "--ignore-running",
        "-z",
    )

    assert main() is None

    fast_resume = FastResume(temp_dir / "a.fastresume")
    assert fast_resume.save_path == "/srv/media/movies/x"
    assert fast_resume.qbt_save_path == "/srv/media/movies/x"
