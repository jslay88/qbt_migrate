"""`--log-file`, asked for in a comment on #70.

The DEBUG log shows the paths each file actually has, which is how users work
out why a pattern did not match. Until now it only went to the console.
"""

import logging

import pytest

from qbt_migrate import __version__
from qbt_migrate.classes import FastResume
from qbt_migrate.cli import configure_logging, main, parse_args


RELEVANT = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}
ROOT = logging.getLogger()
PACKAGE = logging.getLogger("qbt_migrate")
CLI = logging.getLogger("qbt_migrate.cli")


def file_handlers(logger: logging.Logger) -> list[logging.FileHandler]:
    return [h for h in logger.handlers if isinstance(h, logging.FileHandler)]


@pytest.fixture(autouse=True)
def restore_logging():
    """Close the file handlers `main()` adds and put levels back.

    The handlers live on the root logger, which outlives the test; left open
    they keep writing to a deleted temp dir and leak file descriptors.
    """
    levels = PACKAGE.level, CLI.level
    handlers = list(ROOT.handlers)
    yield
    for handler in list(ROOT.handlers):
        if handler not in handlers:
            ROOT.removeHandler(handler)
            handler.close()
    PACKAGE.setLevel(levels[0])
    CLI.setLevel(levels[1])


def test_log_file_defaults_off():
    """No file is written unless asked for."""
    assert parse_args([]).log_file is None
    assert parse_args(["--log-file", "x.log"]).log_file == "x.log"


def test_log_file_gets_debug_at_default_level(
    write_fastresume, temp_dir, cli_args, caplog
):
    """The file has the DEBUG detail even when the console is at INFO."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    write_fastresume("b.fastresume", {"save_path": "/elsewhere"})
    log = temp_dir / "logs" / "migrate.log"
    log.parent.mkdir()
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/some/test",
        "-n",
        "/new",
        "-z",
        "--log-file",
        str(log),
    )

    assert main() is None
    text = log.read_text(encoding="utf-8")
    # INFO lines, with the emoji intact.
    assert "Updated 1 of 1 relevant fastresume file!" in text
    assert "✔️" in text
    # DEBUG lines the console does not show at the default level.
    assert "is not relevant" in text
    assert "Save Path: /elsewhere" in text
    assert " :: DEBUG :: qbt_migrate." in text
    assert f"qbt_migrate {__version__}" in text
    assert FastResume(temp_dir / "a.fastresume").save_path == "/new/path"


def test_console_keeps_its_level_while_the_file_gets_debug(
    temp_dir, monkeypatch
):
    """With nothing configured yet (a real run), the handlers are ours."""
    monkeypatch.setattr(ROOT, "handlers", [])

    configure_logging("INFO", str(temp_dir / "x.log"))
    console, log_file = ROOT.handlers
    # Taken off the patched list now, since monkeypatch restores the original
    # one before the autouse fixture gets to clean up.
    log_file.close()

    assert type(console) is logging.StreamHandler
    assert console.level == logging.INFO
    assert console.formatter._fmt == "%(message)s"
    assert isinstance(log_file, logging.FileHandler)
    assert log_file.level == logging.DEBUG
    assert PACKAGE.level == logging.DEBUG
    assert CLI.level == logging.DEBUG


def test_without_log_file_nothing_changes(temp_dir):
    """Without the flag, levels and handlers are what they always were."""
    # pytest keeps a FileHandler of its own on the root logger.
    before = file_handlers(ROOT)
    configure_logging("INFO")

    assert PACKAGE.level == logging.INFO
    assert file_handlers(ROOT) == before


def test_module_run_as_main_is_logged_too(temp_dir):
    """`python -m qbt_migrate.cli` logs as `__main__`, outside the package."""
    log = temp_dir / "x.log"
    configure_logging("INFO", str(log))
    logging.getLogger("__main__").warning("from main")
    for handler in ROOT.handlers:
        handler.flush()

    assert "from main" in log.read_text(encoding="utf-8")


def test_log_file_appends(write_fastresume, temp_dir, cli_args):
    """A second pass adds to the log instead of replacing the first."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    log = temp_dir / "logs" / "migrate.log"
    log.parent.mkdir()
    log.write_text("earlier run\n", encoding="utf-8")
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/some/test",
        "-n",
        "/new",
        "-z",
        "-d",
        "--log-file",
        str(log),
    )

    assert main() is None
    text = log.read_text(encoding="utf-8")
    assert text.startswith("earlier run\n")
    assert "Nothing was written." in text


@pytest.mark.parametrize("name", ["missing/dir/x.log", "", "."])
def test_unwritable_log_file_is_a_bad_argument(
    write_fastresume, temp_dir, cli_args, caplog, name, monkeypatch
):
    """Exit 2 before anything is touched, like other bad arguments."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    monkeypatch.chdir(temp_dir)
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/some/test",
        "-n",
        "/new",
        "--log-file",
        name,
    )

    assert main() == 2
    assert "Cannot write the log file" in caplog.text
    assert (
        FastResume(temp_dir / "a.fastresume").save_path
        == RELEVANT["save_path"]
    )
    assert list(temp_dir.glob("*.zip")) == []


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("-z", "looks like an option"),
        ("a.fastresume", "qBittorrent data file"),
        ("a.torrent", "qBittorrent data file"),
    ],
)
def test_suspicious_log_file_is_refused(
    write_fastresume, temp_dir, cli_args, caplog, name, reason, monkeypatch
):
    """`--log-file=-z` and qBittorrent's own files are never written to."""
    path = write_fastresume("a.fastresume", dict(RELEVANT))
    before = path.read_bytes()
    monkeypatch.chdir(temp_dir)
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/some/test",
        "-n",
        "/new",
        f"--log-file={name}",
    )

    assert main() == 2
    assert reason in caplog.text
    assert path.read_bytes() == before
    assert not (temp_dir / "-z").exists()
