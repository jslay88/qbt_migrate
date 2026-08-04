"""The CLI must not prompt when there is nobody to answer.

Closes #69 and the second half of #65. Every prompt was unconditional, so any
non-TTY invocation (`docker run` without `-it`, cron, a shell script) died with
a traceback instead of either running or explaining itself. Even a fully
flagged invocation blocked, because `--regex` and `--target-os` were prompted
for whenever they were omitted.
"""

import sys

import pytest

from qbt_migrate.cli import is_interactive, main
from qbt_migrate.enums import TargetOS


RELEVANT = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}


def test_not_interactive_under_captured_stdin():
    # pytest replaces stdin with a non-tty, same as a container without -it.
    assert is_interactive() is False


def test_interactive_when_stdin_is_a_tty(interactive_stdin):
    assert is_interactive() is True


def test_no_stdin_at_all_is_not_interactive(monkeypatch):
    # pythonw and some service hosts hand you sys.stdin is None.
    monkeypatch.setattr(sys, "stdin", None)
    assert is_interactive() is False


def test_fully_flagged_run_does_not_prompt(
    write_fastresume, temp_dir, cli_args
):
    """`-r` and `-t` omitted used to raise EOFError here.

    This is the exact shape of the invocation in #69:
    `docker run ... jslay88/qbt_migrate -e 'G:\\' -n 'T:\\'`
    """
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new")

    assert main() is None

    from qbt_migrate.classes import FastResume

    assert FastResume(temp_dir / "a.fastresume").save_path == "/new/path"


def test_target_os_still_auto_detected_without_prompt(
    write_fastresume, temp_dir, cli_args
):
    write_fastresume(
        "a.fastresume",
        {"save_path": "D:\\Torrents", "qBt-savePath": "D:\\Torrents"},
    )
    cli_args("-b", str(temp_dir), "-e", "D:\\Torrents", "-n", "/torrents")

    assert main() is None

    from qbt_migrate.classes import FastResume

    assert FastResume(temp_dir / "a.fastresume").save_path == "/torrents"


def test_bt_backup_path_defaults_without_prompt(monkeypatch, cli_args):
    """Omitting -b non-interactively uses the platform default."""
    seen = {}

    class MockQBTBatchMove:
        def __init__(self, bt_backup_path=None):
            self.bt_backup_path = "platform-default"

        def run(self, *args, **kwargs):
            seen["bt_backup_path"] = self.bt_backup_path

    monkeypatch.setattr("qbt_migrate.cli.QBTBatchMove", MockQBTBatchMove)
    cli_args("-e", "/a", "-n", "/b", "-t", "Linux")

    assert main() is None
    assert seen["bt_backup_path"] == "platform-default"


@pytest.mark.parametrize(
    "args, missing",
    [
        (("-n", "/new"), "--existing-path/-e"),
        (("-e", "/old"), "--new-path/-n"),
        ((), "--existing-path/-e"),
    ],
)
def test_missing_required_args_explain_themselves(
    temp_dir, cli_args, caplog, args, missing
):
    cli_args("-b", str(temp_dir), *args)

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2

    assert missing in caplog.text
    assert "nobody to prompt" in caplog.text
    assert "-it" in caplog.text


def test_unreadable_file_points_at_skip_bad_files(
    write_fastresume, copy_fastresume, temp_dir, cli_args, caplog
):
    """#65: running without -s threw a bare traceback."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    copy_fastresume("bad.fastresume")
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new")

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 1

    assert "-s/--skip-bad-files" in caplog.text


def test_skip_bad_files_migrates_the_rest(
    write_fastresume, copy_fastresume, temp_dir, cli_args
):
    write_fastresume("a.fastresume", dict(RELEVANT))
    copy_fastresume("bad.fastresume")
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", "-s")

    assert main() is None

    from qbt_migrate.classes import FastResume

    assert FastResume(temp_dir / "a.fastresume").save_path == "/new/path"


def test_bad_bt_backup_path_explains_itself(temp_dir, cli_args, caplog):
    cli_args(
        "-b",
        str(temp_dir / "nope"),
        "-e",
        "/some/test",
        "-n",
        "/new",
        "-t",
        "Linux",
    )

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2

    assert "not a directory" in caplog.text


def test_explicit_flags_still_win_when_interactive(
    monkeypatch, write_fastresume, temp_dir, cli_args, interactive_stdin
):
    """Passing a flag must skip its prompt even with a tty attached."""

    def no_input(_):
        raise AssertionError("should not have prompted")

    monkeypatch.setattr("builtins.input", no_input)
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/some/test",
        "-n",
        "/new",
        "-r",
        "-t",
        "Linux",
    )

    assert main() is None


def test_resolve_target_os_handles_explicit_values():
    from qbt_migrate.cli import resolve_target_os

    assert resolve_target_os("Windows", "/a", "/b") is TargetOS.WINDOWS
    assert resolve_target_os("Mac", "/a", "/b") is TargetOS.POSIX
    assert resolve_target_os("", "/a", "/b") is None
