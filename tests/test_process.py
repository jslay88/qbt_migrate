"""Finding and stopping a running qBittorrent."""

import subprocess
import sys

import pytest

from qbt_migrate import process
from qbt_migrate.process import (
    Process,
    find_processes,
    stop_processes,
)


@pytest.fixture
def fake_proc(monkeypatch, temp_dir):
    """Build a fake /proc tree. Returns a function taking {pid: comm}."""

    def _build(entries: dict[int, str]) -> None:
        for pid, comm in entries.items():
            directory = temp_dir / str(pid)
            directory.mkdir()
            (directory / "comm").write_text(f"{comm}\n")
        # Non numeric entries and a pid with no readable comm, both of which a
        # real /proc has.
        (temp_dir / "self").mkdir()
        (temp_dir / "9999").mkdir()
        monkeypatch.setattr(process, "PROC_ROOT", temp_dir)

    return _build


@pytest.fixture
def fake_command(monkeypatch):
    """Capture commands and return canned stdout."""
    calls = []

    def _install(stdout: str = "", raises: Exception | None = None):
        def run(command, **kwargs):
            calls.append(command)
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(command, 0, stdout, "")

        monkeypatch.setattr(process.subprocess, "run", run)
        return calls

    return _install


@pytest.mark.parametrize(
    "comm, expected",
    [
        ("qbittorrent", True),
        ("qbittorrent-nox", True),
        ("qBittorrent", True),
        ("qBittorrent.exe", True),
        ("/usr/bin/qbittorrent", True),
        ("qbittorrent-nox.exe", True),
        ("qbittorrentd", False),
        ("firefox", False),
        ("", False),
    ],
)
def test_name_matching(comm, expected):
    assert process._matches(comm) is expected


def test_linux_detection(monkeypatch, fake_proc):
    monkeypatch.setattr(sys, "platform", "linux")
    fake_proc({101: "qbittorrent", 202: "firefox", 303: "qbittorrent-nox"})

    found = find_processes()

    assert sorted((p.pid, p.name) for p in found) == [
        (101, "qbittorrent"),
        (303, "qbittorrent-nox"),
    ]


def test_linux_detection_when_proc_is_unreadable(monkeypatch, temp_dir):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(process, "PROC_ROOT", temp_dir / "nope")

    assert find_processes() == []


def test_macos_detection(monkeypatch, fake_command):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = fake_command("  501 qbittorrent\n  502 Finder\nbad line\n")

    found = find_processes()

    assert found == [Process(501, "qbittorrent")]
    assert calls == [["ps", "-Ao", "pid=,comm="]]


def test_windows_detection(monkeypatch, fake_command):
    monkeypatch.setattr(sys, "platform", "win32")
    calls = fake_command(
        '"qBittorrent.exe","4242","Console","1","210,000 K"\n'
        '"explorer.exe","900","Console","1","90,000 K"\n'
        '"malformed"\n'
    )

    found = find_processes()

    assert found == [Process(4242, "qBittorrent.exe")]
    assert calls == [["tasklist", "/FO", "CSV", "/NH"]]


def test_detection_survives_a_missing_command(monkeypatch, fake_command):
    monkeypatch.setattr(sys, "platform", "darwin")
    fake_command(raises=FileNotFoundError("no ps"))

    assert find_processes() == []


def test_stop_signals_then_waits(monkeypatch):
    """The wait matters more than the signal.

    A process still being listed means it has not finished writing yet.
    """
    signalled = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        process.os, "kill", lambda pid, sig: signalled.append((pid, sig))
    )
    monkeypatch.setattr(process.time, "sleep", lambda _: None)

    # Alive for the first two polls, gone on the third.
    polls = iter(
        [[Process(1, "qbittorrent")], [Process(1, "qbittorrent")], []]
    )
    monkeypatch.setattr(process, "find_processes", lambda: next(polls))

    remaining = stop_processes([Process(1, "qbittorrent")])

    assert remaining == []
    assert signalled == [(1, process.signal.SIGTERM)]


def test_stop_reports_what_would_not_die(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(process.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(process.time, "sleep", lambda _: None)
    stubborn = Process(1, "qbittorrent")
    monkeypatch.setattr(process, "find_processes", lambda: [stubborn])

    assert stop_processes([stubborn], timeout=0) == [stubborn]


def test_stop_uses_taskkill_without_force_on_windows(
    monkeypatch, fake_command
):
    """/F would skip the resume data flush, which is the whole point."""
    monkeypatch.setattr(sys, "platform", "win32")
    calls = fake_command("")
    monkeypatch.setattr(process, "find_processes", lambda: [])

    stop_processes([Process(7, "qBittorrent.exe")])

    assert calls == [["taskkill", "/PID", "7"]]
    assert not any("/F" in call for call in calls)


def test_stop_survives_a_process_that_already_exited(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(process.os, "kill", gone)
    monkeypatch.setattr(process, "find_processes", lambda: [])

    assert stop_processes([Process(1, "qbittorrent")]) == []


def test_process_str_is_readable():
    assert str(Process(42, "qbittorrent")) == "qbittorrent (pid 42)"
