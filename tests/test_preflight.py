"""Refusing to write while qBittorrent is running.

Editing `.fastresume` files underneath a running client accomplishes nothing:
it holds resume data in memory and writes it back out on exit, so the changes
are silently reverted. The README has warned about this since 2.0, which only
helps people who read it.
"""

import pytest

from qbt_migrate.classes import FastResume
from qbt_migrate.cli import main
from qbt_migrate.process import Process


RELEVANT = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}
RUNNING = [Process(4242, "qbittorrent")]


@pytest.fixture
def qbittorrent_running(monkeypatch):
    """Override the autouse fixture that pretends nothing is running."""
    monkeypatch.setattr("qbt_migrate.cli.find_processes", lambda: RUNNING)


@pytest.fixture
def stop_succeeds(monkeypatch):
    calls = []

    def stop(processes, *args, **kwargs):
        calls.append(processes)
        return []

    monkeypatch.setattr("qbt_migrate.cli.stop_processes", stop)
    return calls


@pytest.fixture
def stop_fails(monkeypatch):
    monkeypatch.setattr(
        "qbt_migrate.cli.stop_processes", lambda processes, *a, **k: processes
    )


def test_refuses_non_interactively(
    write_fastresume, temp_dir, cli_args, caplog, qbittorrent_running
):
    path = write_fastresume("a.fastresume", dict(RELEVANT))
    before = path.read_bytes()
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new")

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2

    assert "Refusing to run while qBittorrent is running" in caplog.text
    assert "-k/--stop-qbittorrent" in caplog.text
    assert path.read_bytes() == before


def test_stop_flag_stops_then_migrates(
    write_fastresume,
    temp_dir,
    cli_args,
    qbittorrent_running,
    stop_succeeds,
):
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", "-k", "-z")

    assert main() is None

    assert stop_succeeds == [RUNNING]
    assert FastResume(temp_dir / "a.fastresume").save_path == "/new/path"


def test_bails_when_it_will_not_exit(
    write_fastresume,
    temp_dir,
    cli_args,
    caplog,
    qbittorrent_running,
    stop_fails,
):
    """Never proceed on a maybe. A half exited client is still writing."""
    path = write_fastresume("a.fastresume", dict(RELEVANT))
    before = path.read_bytes()
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", "-k")

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2

    assert "did not exit" in caplog.text
    assert "File -> Exit" in caplog.text
    assert path.read_bytes() == before


def test_prompts_and_stops_when_interactive(
    monkeypatch,
    write_fastresume,
    temp_dir,
    cli_args,
    interactive_stdin,
    qbittorrent_running,
    stop_succeeds,
):
    write_fastresume("a.fastresume", dict(RELEVANT))
    # -r and -t are passed so the preflight is the only prompt that fires.
    monkeypatch.setattr("builtins.input", lambda _: "y")
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
        "-z",
    )

    assert main() is None
    assert stop_succeeds == [RUNNING]


def test_declining_the_prompt_bails(
    monkeypatch,
    write_fastresume,
    temp_dir,
    cli_args,
    caplog,
    interactive_stdin,
    qbittorrent_running,
):
    path = write_fastresume("a.fastresume", dict(RELEVANT))
    before = path.read_bytes()
    monkeypatch.setattr("builtins.input", lambda _: "n")
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

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2

    assert "Close qBittorrent and run again" in caplog.text
    assert path.read_bytes() == before


def test_ignore_running_overrides_with_a_warning(
    write_fastresume, temp_dir, cli_args, caplog, qbittorrent_running
):
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/some/test",
        "-n",
        "/new",
        "--ignore-running",
        "-z",
    )

    with caplog.at_level("WARNING", logger="qbt_migrate.cli"):
        assert main() is None

    assert "overwrite these changes from memory" in caplog.text
    assert FastResume(temp_dir / "a.fastresume").save_path == "/new/path"


def test_dry_run_does_not_care(
    write_fastresume, temp_dir, cli_args, qbittorrent_running
):
    """A dry run writes nothing, so it is the safe thing to reach for first."""
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", "-d")

    assert main() is None


def test_nothing_running_is_silent(
    write_fastresume, temp_dir, cli_args, caplog
):
    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new", "-z")

    with caplog.at_level("WARNING", logger="qbt_migrate.cli"):
        assert main() is None

    assert "qBittorrent is running" not in caplog.text


def test_flags_default_off():
    from qbt_migrate.cli import parse_args

    args = parse_args([])
    assert args.stop_qbittorrent is False
    assert args.ignore_running is False
    assert parse_args(["-k"]).stop_qbittorrent is True
    assert parse_args(["--stop-qbittorrent"]).stop_qbittorrent is True
    assert parse_args(["--ignore-running"]).ignore_running is True
