"""Failures during a batch have to be reported, not swallowed.

`run()` used to spawn one unjoined `Thread` per matched file and never collect
results, so an exception in a worker printed to stderr while `run()` logged
success and the CLI exited 0. A partial migration was indistinguishable from a
clean one, which is a large part of why users reported needing repeated passes.
"""

import pytest

import qbt_migrate
from qbt_migrate.classes import QBTBatchMove
from qbt_migrate.cli import main
from qbt_migrate.exceptions import FastResumeUpdateError, QBTMigrateError


RELEVANT = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}


@pytest.fixture
def failing_replace_paths(monkeypatch):
    """Make `replace_paths` raise for fastresume files matching `names`."""

    def _fail(*names: str):
        original = qbt_migrate.classes.FastResume.replace_paths

        def replace_paths(self, *args, **kwargs):
            if self.file_path.name in names:
                raise PermissionError(f"[Errno 13] denied: {self.file_path}")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(
            qbt_migrate.classes.FastResume, "replace_paths", replace_paths
        )

    return _fail


def test_run_raises_when_a_worker_fails(
    write_fastresume, temp_dir, failing_replace_paths
):
    path = write_fastresume("a.fastresume", dict(RELEVANT))
    failing_replace_paths("a.fastresume")

    qbt = QBTBatchMove(str(temp_dir))
    with pytest.raises(FastResumeUpdateError) as excinfo:
        qbt.run("/some/test", "/new", create_backup=False)

    assert list(excinfo.value.failures) == [path]
    assert isinstance(excinfo.value.failures[path], PermissionError)
    assert "a.fastresume" in str(excinfo.value)


def test_failure_is_a_qbt_migrate_error(write_fastresume, temp_dir):
    # Callers should be able to catch the package base class.
    assert issubclass(FastResumeUpdateError, QBTMigrateError)


def test_good_files_still_migrate_when_one_fails(
    write_fastresume, temp_dir, failing_replace_paths
):
    """One bad file must not abandon the rest of the batch."""
    write_fastresume("bad.fastresume", dict(RELEVANT))
    good = write_fastresume("good.fastresume", dict(RELEVANT))
    failing_replace_paths("bad.fastresume")

    qbt = QBTBatchMove(str(temp_dir))
    with pytest.raises(FastResumeUpdateError) as excinfo:
        qbt.run("/some/test", "/new", create_backup=False)

    assert [p.name for p in excinfo.value.failures] == ["bad.fastresume"]
    migrated = qbt_migrate.classes.FastResume(good)
    assert migrated.save_path == "/new/path"


def test_run_reports_counts(write_fastresume, temp_dir, caplog):
    write_fastresume("a.fastresume", dict(RELEVANT))
    write_fastresume("b.fastresume", dict(RELEVANT))

    qbt = QBTBatchMove(str(temp_dir))
    with caplog.at_level("INFO", logger="qbt_migrate.classes"):
        qbt.run("/some/test", "/new", create_backup=False)

    assert "Updated 2 of 2 relevant fastresume files!" in caplog.text


def test_run_succeeds_quietly_with_nothing_to_do(temp_dir, caplog):
    qbt = QBTBatchMove(str(temp_dir))
    with caplog.at_level("INFO", logger="qbt_migrate.classes"):
        qbt.run("/some/test", "/new", create_backup=False)

    assert "Updated 0 of 0 relevant fastresume files!" in caplog.text


def test_max_workers_is_forwarded(write_fastresume, temp_dir, monkeypatch):
    seen = {}
    original = qbt_migrate.classes.ThreadPoolExecutor

    def executor(max_workers=None):
        seen["max_workers"] = max_workers
        return original(max_workers=max_workers)

    monkeypatch.setattr(qbt_migrate.classes, "ThreadPoolExecutor", executor)
    write_fastresume("a.fastresume", dict(RELEVANT))

    QBTBatchMove(str(temp_dir)).run(
        "/some/test", "/new", create_backup=False, max_workers=2
    )
    assert seen["max_workers"] == 2


@pytest.fixture
def non_interactive_cli(monkeypatch, cli_args, temp_dir):
    """Invoke the CLI with every prompt answered with a bare enter.

    `-r` and `-t` still prompt when not passed, even though everything else was
    supplied. That is #69, fixed later in the stack.
    """

    def _run() -> int | None:
        monkeypatch.setattr("builtins.input", lambda _: "")
        cli_args("-b", str(temp_dir), "-e", "/some/test", "-n", "/new")
        return main()

    return _run


def test_cli_exits_non_zero_when_files_fail(
    write_fastresume, non_interactive_cli, failing_replace_paths
):
    write_fastresume("a.fastresume", dict(RELEVANT))
    failing_replace_paths("a.fastresume")

    assert non_interactive_cli() == 1


def test_cli_exits_zero_on_success(write_fastresume, non_interactive_cli):
    write_fastresume("a.fastresume", dict(RELEVANT))

    assert non_interactive_cli() is None
