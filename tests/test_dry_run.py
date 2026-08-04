"""`--dry-run`: say what would happen, write nothing.

Every bad outcome reported against this tool was someone finding out what it
did after it did it. Both reporters on #75 watched qBittorrent start relocating
files before they understood why.
"""

import pytest

from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.cli import main
from qbt_migrate.enums import TargetOS
from qbt_migrate.plans import MigrationPlan, PathChange, diff_data


WINDOWS_KEYS = {
    "save_path": "S:\\Pictures\\",
    "qBt-savePath": "S:\\Pictures\\",
    "qBt-downloadPath": "S:\\Incomplete\\",
    "mapped_files": ["S:\\Pictures\\a.jpg", "S:\\Pictures\\b.jpg"],
}


def test_plan_reports_every_changing_key(write_fastresume):
    path = write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    plan = FastResume(path).plan_paths(
        "S:\\", "/mnt/s/", target_os=TargetOS.POSIX
    )

    assert plan.file_path == path
    assert bool(plan) is True
    assert plan.error is None
    changes = {c.key: (c.old, c.new) for c in plan.changes}
    assert changes["save_path"] == ("S:\\Pictures\\", "/mnt/s/Pictures/")
    assert changes["qBt-savePath"] == ("S:\\Pictures\\", "/mnt/s/Pictures/")
    assert changes["qBt-downloadPath"] == (
        "S:\\Incomplete\\",
        "/mnt/s/Incomplete/",
    )


def test_plan_summarizes_mapped_files(write_fastresume):
    path = write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    plan = FastResume(path).plan_paths(
        "S:\\", "/mnt/s/", target_os=TargetOS.POSIX
    )

    mapped = next(c for c in plan.changes if c.key == "mapped_files")
    assert mapped.is_list is True
    assert (mapped.changed_entries, mapped.total_entries) == (2, 2)
    assert mapped.old == "S:\\Pictures\\a.jpg"
    assert mapped.new == "/mnt/s/Pictures/a.jpg"


def test_planning_does_not_mutate_the_object(write_fastresume):
    path = write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    fast_resume = FastResume(path)
    fast_resume.plan_paths("S:\\", "/mnt/s/", target_os=TargetOS.POSIX)

    assert fast_resume.save_path == "S:\\Pictures\\"
    assert fast_resume.qbt_save_path == "S:\\Pictures\\"
    assert fast_resume.mapped_files == WINDOWS_KEYS["mapped_files"]


def test_planning_does_not_touch_disk(write_fastresume, temp_dir):
    path = write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    before = path.read_bytes()

    FastResume(path).plan_paths("S:\\", "/mnt/s/", target_os=TargetOS.POSIX)

    assert path.read_bytes() == before
    assert list(temp_dir.glob("*.bkup")) == []
    assert list(temp_dir.glob("*.zip")) == []


def test_plan_matches_what_applying_actually_does(write_fastresume):
    """The preview has to agree with the apply, or it is worse than nothing."""
    planned = FastResume(
        write_fastresume("a.fastresume", dict(WINDOWS_KEYS))
    ).plan_paths("S:\\", "/mnt/s/", target_os=TargetOS.POSIX)

    applied = FastResume(write_fastresume("b.fastresume", dict(WINDOWS_KEYS)))
    applied.replace_paths(
        "S:\\",
        "/mnt/s/",
        target_os=TargetOS.POSIX,
        save_file=False,
        create_backup=False,
    )

    for change in planned.changes:
        if change.key == "mapped_files":
            assert applied.mapped_files is not None
            assert applied.mapped_files[0] == change.new
        else:
            assert applied._data[change.key] == change.new


def test_relative_mapped_files_are_not_reported(write_fastresume):
    """`mapped_files` holds relative paths unless files were renamed.

    Those are unaffected by a root path change, so they must not show up in the
    preview as noise on every single torrent.
    """
    path = write_fastresume(
        "rel.fastresume",
        {
            "save_path": "S:\\Pictures\\",
            "qBt-savePath": "S:\\Pictures\\",
            "mapped_files": ["album/a.jpg", "album/b.jpg"],
        },
    )
    plan = FastResume(path).plan_paths(
        "S:\\", "/mnt/s/", target_os=TargetOS.POSIX
    )

    assert [c.key for c in plan.changes] == ["save_path", "qBt-savePath"]


def test_plan_is_empty_when_nothing_would_change(write_fastresume):
    path = write_fastresume(
        "done.fastresume",
        {"save_path": "/mnt/s/Pictures", "qBt-savePath": "/mnt/s/Pictures"},
    )
    plan = FastResume(path).plan_paths("/mnt/s", "/mnt/s")

    assert bool(plan) is False
    assert plan.changes == ()


def test_batch_plan_collects_all_files(write_fastresume, temp_dir):
    write_fastresume("a.fastresume", dict(WINDOWS_KEYS))
    write_fastresume("b.fastresume", dict(WINDOWS_KEYS))

    summary = QBTBatchMove(str(temp_dir)).plan(
        "S:\\", "/mnt/s/", target_os=TargetOS.POSIX
    )

    assert summary.discovered == 2
    assert len(summary.changing) == 2
    assert summary.failing == []


def test_batch_plan_surfaces_files_that_would_fail(
    write_fastresume, temp_dir, monkeypatch
):
    """Knowing which files would break is the point of asking first."""
    write_fastresume("a.fastresume", dict(WINDOWS_KEYS))

    def boom(self, *args, **kwargs):
        raise ValueError("Cannot set an empty save path")

    monkeypatch.setattr(FastResume, "plan_paths", boom)

    summary = QBTBatchMove(str(temp_dir)).plan("S:\\", "/mnt/s/")

    assert summary.discovered == 1
    assert summary.changing == []
    assert len(summary.failing) == 1
    assert "empty save path" in summary.failing[0].error


def test_batch_plan_rejects_a_bad_backup_path(temp_dir):
    qbt = QBTBatchMove(str(temp_dir / "nope"))
    with pytest.raises(NotADirectoryError):
        qbt.plan("S:\\", "/mnt/s/")


def test_cli_dry_run_writes_nothing(write_fastresume, temp_dir, cli_args):
    path = write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    before = path.read_bytes()
    cli_args("-b", str(temp_dir), "-e", "S:\\", "-n", "/mnt/s/", "--dry-run")

    assert main() is None

    assert path.read_bytes() == before
    assert list(temp_dir.glob("fastresume_backup*.zip")) == []


@pytest.mark.parametrize("flag", ["-d", "--dry-run"])
def test_cli_dry_run_output(
    write_fastresume, temp_dir, cli_args, caplog, flag
):
    write_fastresume("win.fastresume", dict(WINDOWS_KEYS))
    cli_args("-b", str(temp_dir), "-e", "S:\\", "-n", "/mnt/s/", flag)

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        main()

    # Quoted, and not repr-escaped: the real value has single backslashes.
    assert "'S:\\Pictures\\' -> '/mnt/s/Pictures/'" in caplog.text
    assert "2 of 2 entries" in caplog.text
    assert "1 of 1 relevant fastresume file would be updated" in caplog.text
    assert "Nothing was written" in caplog.text


def test_cli_dry_run_reports_already_matching(
    write_fastresume, temp_dir, cli_args, caplog
):
    write_fastresume(
        "done.fastresume",
        {"save_path": "/mnt/s/Pictures", "qBt-savePath": "/mnt/s/Pictures"},
    )
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/mnt/s",
        "-n",
        "/mnt/s",
        "-d",
        "-t",
        "Linux",
    )

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        main()

    assert "0 of 1 relevant fastresume file would be updated" in caplog.text
    assert "1 already match" in caplog.text


def test_cli_dry_run_truncates_large_libraries(
    write_fastresume, temp_dir, cli_args, caplog
):
    for i in range(25):
        write_fastresume(f"t{i:03}.fastresume", dict(WINDOWS_KEYS))
    cli_args("-b", str(temp_dir), "-e", "S:\\", "-n", "/mnt/s/", "-d")

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        main()

    assert "... and 5 more" in caplog.text
    assert "25 of 25 relevant fastresume files would be updated" in caplog.text


def test_cli_dry_run_lists_everything_at_debug(
    write_fastresume, temp_dir, cli_args, caplog
):
    for i in range(25):
        write_fastresume(f"t{i:03}.fastresume", dict(WINDOWS_KEYS))
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "S:\\",
        "-n",
        "/mnt/s/",
        "-d",
        "-l",
        "DEBUG",
    )

    with caplog.at_level("DEBUG", logger="qbt_migrate.cli"):
        main()

    assert "more. Re-run with" not in caplog.text
    assert "t024.fastresume" in caplog.text


def test_cli_dry_run_reports_failures(
    write_fastresume, temp_dir, cli_args, caplog, monkeypatch
):
    write_fastresume("a.fastresume", dict(WINDOWS_KEYS))

    def boom(self, *args, **kwargs):
        raise ValueError("Cannot set an empty save path")

    monkeypatch.setattr(FastResume, "plan_paths", boom)
    cli_args("-b", str(temp_dir), "-e", "S:\\", "-n", "/mnt/s/", "-d")

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        assert main() is None

    assert "would fail: Cannot set an empty save path" in caplog.text
    assert "1 would fail" in caplog.text


def test_cli_dry_run_on_unreadable_file(
    write_fastresume, copy_fastresume, temp_dir, cli_args, caplog
):
    write_fastresume("a.fastresume", dict(WINDOWS_KEYS))
    copy_fastresume("bad.fastresume")
    cli_args("-b", str(temp_dir), "-e", "S:\\", "-n", "/mnt/s/", "-d")

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 1

    assert "-s/--skip-bad-files" in caplog.text


def test_cli_dry_run_on_bad_backup_path(temp_dir, cli_args, caplog):
    cli_args(
        "-b",
        str(temp_dir / "nope"),
        "-e",
        "S:\\",
        "-n",
        "/mnt/s/",
        "-d",
        "-t",
        "Linux",
    )

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2

    assert "not a directory" in caplog.text


def test_dry_run_flag_defaults_off():
    from qbt_migrate.cli import parse_args

    assert parse_args([]).dry_run is False
    assert parse_args(["-d"]).dry_run is True
    assert parse_args(["--dry-run"]).dry_run is True


def test_diff_ignores_non_string_and_absent_values():
    """Bencode is schemaless, so keys can be missing or the wrong type."""
    plan = diff_data(
        write_path := __import__("pathlib").Path("x.fastresume"),
        {"save_path": "/old", "mapped_files": "not-a-list"},
        {"save_path": 42, "mapped_files": "not-a-list"},
    )
    assert plan.file_path == write_path
    assert plan.changes == ()


def test_path_change_is_not_a_list_by_default():
    assert PathChange("save_path", "/a", "/b").is_list is False


def test_empty_plan_is_falsey():
    import pathlib

    assert not MigrationPlan(file_path=pathlib.Path("x"))
