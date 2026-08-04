"""Finding and stopping a running qBittorrent.

qBittorrent holds resume data in memory and writes `.fastresume` files out on
shutdown. Editing them underneath a running client means the client overwrites
your changes from memory the moment it exits, which looks exactly like the tool
silently doing nothing. The README has warned about this since 2.0, which only
helps the people who read it.

Detection is best effort by design. Inside a container `/proc` shows only
the container's own processes, so a qBittorrent running on the host is
invisible and nothing here will find it.
"""

import csv
import logging
import os
import signal

# Only ever invoked with a literal argument list and shell=False, see _run.
import subprocess  # nosec B404
import sys
import time
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)

# Basenames qBittorrent runs under, lowercased and with any .exe suffix
# removed. Covers the GUI build, the headless build, Flatpak, and AppImage,
# all of which keep one of these two names.
PROCESS_NAMES = frozenset({"qbittorrent", "qbittorrent-nox"})

# Monkeypatched in tests. /proc/<pid>/comm is world readable, unlike
# /proc/<pid>/exe, so this works for processes owned by other users too.
PROC_ROOT = Path("/proc")

DEFAULT_TIMEOUT = 30.0
POLL_INTERVAL = 0.25


@dataclass(frozen=True)
class Process:
    pid: int
    name: str

    def __str__(self) -> str:
        return f"{self.name} (pid {self.pid})"


def _matches(name: str) -> bool:
    """Is this process name one of qBittorrent's?"""
    basename = Path(name.strip()).name
    return basename.removesuffix(".exe").lower() in PROCESS_NAMES


def _run(command: list[str]) -> str:
    """Run a fixed command and return stdout, or "" if it is unavailable.

    Every caller passes a literal argument list with no user input and no
    shell, so there is nothing here to inject into.
    """
    try:
        result = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"Could not run {command[0]}: {e}")
        return ""
    return result.stdout


def _linux_processes() -> list[Process]:
    found: list[Process] = []
    try:
        entries = sorted(PROC_ROOT.iterdir())
    except OSError as e:
        logger.debug(f"Could not read {PROC_ROOT}: {e}")
        return found
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except OSError:
            # Exited between listing and reading, or not readable.
            continue
        if _matches(comm):
            found.append(Process(int(entry.name), comm))
    return found


def _ps_processes() -> list[Process]:
    found: list[Process] = []
    for line in _run(["ps", "-Ao", "pid=,comm="]).splitlines():
        pid, _, name = line.strip().partition(" ")
        if pid.isdigit() and _matches(name):
            found.append(Process(int(pid), Path(name.strip()).name))
    return found


def _tasklist_processes() -> list[Process]:
    found: list[Process] = []
    output = _run(["tasklist", "/FO", "CSV", "/NH"])
    for row in csv.reader(output.splitlines()):
        if len(row) >= 2 and row[1].strip().isdigit() and _matches(row[0]):
            found.append(Process(int(row[1].strip()), row[0].strip()))
    return found


def find_processes() -> list[Process]:
    """Every running qBittorrent this process can see."""
    if sys.platform.startswith("win32"):
        return _tasklist_processes()
    if sys.platform.startswith("linux"):
        return _linux_processes()
    return _ps_processes()


def _request_stop(process: Process) -> None:
    """Ask a process to exit cleanly.

    Deliberately not a hard kill. qBittorrent flushes resume data during
    shutdown, and skipping that is how you end up migrating a half written set
    of files.
    """
    logger.debug(f"Asking {process} to exit...")
    if sys.platform.startswith("win32"):
        # Windows has no SIGTERM. taskkill without /F posts WM_CLOSE, which is
        # the equivalent of choosing File -> Exit.
        _run(["taskkill", "/PID", str(process.pid)])
        return
    try:
        os.kill(process.pid, signal.SIGTERM)
    except OSError as e:
        logger.debug(f"Could not signal {process}: {e}")


def stop_processes(
    processes: list[Process],
    timeout: float = DEFAULT_TIMEOUT,
) -> list[Process]:
    """Ask every process to exit, then wait for them to actually be gone.

    Returns whatever is still running when `timeout` expires. Waiting for the
    process to disappear is the only reliable signal that its resume data has
    finished being written.

    :param processes: Processes to stop.
    :param timeout: Seconds to wait for exit.
    :return: Processes still running.
    """
    for process in processes:
        _request_stop(process)

    logger.info("⏳ Waiting for qBittorrent to finish writing and exit...")
    deadline = time.monotonic() + timeout
    remaining = _still_running(processes)
    while remaining and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        remaining = _still_running(processes)

    if remaining:
        logger.debug(f"Still running after {timeout}s: {remaining}")
    else:
        logger.info("✔️ qBittorrent has exited.")
    return remaining


def _still_running(processes: list[Process]) -> list[Process]:
    live = {process.pid for process in find_processes()}
    return [process for process in processes if process.pid in live]
