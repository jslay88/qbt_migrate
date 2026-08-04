import shutil
import sys
import tempfile
from pathlib import Path
from tempfile import NamedTemporaryFile

import bencodepy
import pytest


TEST_FILES = Path(__file__).parent / "test_files"


@pytest.fixture
def test_files() -> Path:
    """Directory holding the `.fastresume` fixtures.

    Resolved from `__file__` rather than the working directory so the suite
    passes no matter where pytest is invoked from.
    """
    return TEST_FILES


@pytest.fixture
def temp_dir():
    path = Path(tempfile.mkdtemp())
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def temp_file():
    with NamedTemporaryFile("w", delete=False) as f:
        yield f.name, f
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def copy_fastresume(temp_dir):
    """Copy `.fastresume` fixtures into a temp dir and return the paths.

    Tests mutate `FastResume` objects, so they must never be pointed at the
    checked-in fixtures directly.
    """

    def _copy(pattern: str = "*.fastresume") -> list[Path]:
        copied = []
        for source in sorted(TEST_FILES.glob(pattern)):
            target = temp_dir / source.name
            shutil.copy(source, target)
            copied.append(target)
        return copied

    return _copy


@pytest.fixture
def write_fastresume(temp_dir):
    """Write a `.fastresume` from a dict and return its path.

    Preferred over adding more binary fixtures when the point of the test is
    the exact contents of the keys.
    """
    bencode = bencodepy.Bencode(encoding="utf-8", encoding_fallback="all")

    def _write(name: str, data: dict) -> Path:
        path = temp_dir / name
        bencode.write(data, path)
        return path

    return _write


@pytest.fixture
def fastresume_path(copy_fastresume):
    """Path to a single named `.fastresume` fixture, copied to a temp dir."""

    def _path(name: str) -> Path:
        return copy_fastresume(name)[0]

    return _path


@pytest.fixture
def linux_env(monkeypatch):
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.fixture
def interactive_stdin(monkeypatch):
    """Make the CLI believe a human is attached to stdin.

    Under pytest stdin is replaced with a non-tty capture object, which is the
    same situation as `docker run` without `-it`, so prompt-driven tests have
    to opt back in.
    """

    class FakeTTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", FakeTTY())


@pytest.fixture
def cli_args(monkeypatch):
    """Set `sys.argv` for a `main()` invocation.

    Tests that call `main()` without this parse pytest's own arguments, so
    running the suite as `pytest -q` fails them with `SystemExit: 2`.
    """

    def _set(*args: str) -> None:
        monkeypatch.setattr(sys, "argv", ["qbt_migrate", *args])

    return _set
