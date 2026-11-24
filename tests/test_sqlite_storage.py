"""qBittorrent's SQLite resume storage is refused, not silently ignored.

With "SQLite database (experimental)" selected, qBittorrent keeps resume data
in `torrents.db` next to BT_backup and loads torrents from it on start. The
run used to find no `.fastresume` files, log "Updated 0 of 0" and exit 0.
"""

import pytest

from qbt_migrate.classes import FastResume
from qbt_migrate.cli import main
from qbt_migrate.methods import find_sqlite_resume_data


RELEVANT = {"save_path": "/some/test/path", "qBt-savePath": "/some/test/path"}


@pytest.fixture
def profile(temp_dir):
    """A qBittorrent data directory with an empty BT_backup inside.

    Nested so `torrents.db` lands in a directory the test owns, not in the
    shared parent of `temp_dir`.
    """
    bt_backup = temp_dir / "qBittorrent" / "BT_backup"
    bt_backup.mkdir(parents=True)
    return bt_backup


def test_finds_torrents_db_next_to_bt_backup(profile):
    """The sibling of BT_backup, where qBittorrent puts it, is found."""
    database = profile.parent / "torrents.db"
    database.write_bytes(b"SQLite format 3\x00")

    assert find_sqlite_resume_data(profile) == database
    assert find_sqlite_resume_data(str(profile)) == database


def test_finds_torrents_db_from_inside_bt_backup(profile, monkeypatch):
    """`-b .` run inside BT_backup still looks in the parent directory."""
    database = profile.parent / "torrents.db"
    database.write_bytes(b"SQLite format 3\x00")
    monkeypatch.chdir(profile)

    found = find_sqlite_resume_data(".")
    # samefile: the working directory may come back with symlinks resolved.
    assert found is not None and found.samefile(database)


def test_cli_refuses_with_relative_bt_backup(
    profile, write_fastresume, cli_args, monkeypatch
):
    """The CLI path of the same case: refused, file untouched."""
    (profile.parent / "torrents.db").write_bytes(b"SQLite format 3\x00")
    path = profile / "a.fastresume"
    write_fastresume("a.fastresume", dict(RELEVANT)).rename(path)
    monkeypatch.chdir(profile)
    cli_args("-b", ".", "-e", "/some/test", "-n", "/new", "-z")

    assert main() == 2
    assert FastResume(path).save_path == RELEVANT["save_path"]


def test_nothing_found_without_torrents_db(profile):
    """Fastresume-only profiles are left alone."""
    assert find_sqlite_resume_data(profile) is None


def test_a_directory_named_torrents_db_is_not_a_database(profile):
    """Only a regular file counts."""
    (profile.parent / "torrents.db").mkdir()

    assert find_sqlite_resume_data(profile) is None


@pytest.mark.parametrize("dry_run", [(), ("-d",)])
def test_cli_refuses_sqlite_storage(profile, cli_args, caplog, dry_run):
    """Exit 2 with the switch-back steps instead of "Updated 0 of 0"."""
    (profile.parent / "torrents.db").write_bytes(b"SQLite format 3\x00")
    cli_args("-b", str(profile), "-e", "/some/test", "-n", "/new", *dry_run)

    assert main() == 2
    assert "torrents.db" in caplog.text
    assert "SQLite" in caplog.text
    assert '"Fastresume files"' in caplog.text
    assert "move it somewhere else" in caplog.text
    assert "Updated 0 of 0" not in caplog.text
    assert list(profile.iterdir()) == []


def test_cli_refuses_stale_fastresume_files_next_to_torrents_db(
    profile, write_fastresume, cli_args, caplog
):
    """Files left over from before the switch are not what qBittorrent loads.

    Editing them would report success while changing nothing that matters.
    """
    (profile.parent / "torrents.db").write_bytes(b"SQLite format 3\x00")
    path = profile / "a.fastresume"
    write_fastresume("a.fastresume", dict(RELEVANT)).rename(path)
    cli_args("-b", str(profile), "-e", "/some/test", "-n", "/new")

    assert main() == 2
    assert FastResume(path).save_path == RELEVANT["save_path"]
    assert sorted(p.name for p in profile.iterdir()) == ["a.fastresume"]


def test_cli_refuses_before_prompting(profile, cli_args, interactive_stdin):
    """No point asking for paths that cannot be applied."""
    (profile.parent / "torrents.db").write_bytes(b"SQLite format 3\x00")
    cli_args("-b", str(profile))

    def no_input(prompt):
        raise AssertionError(f"prompted: {prompt}")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("builtins.input", no_input)
        assert main() == 2


def test_cli_runs_normally_without_torrents_db(
    profile, write_fastresume, cli_args
):
    """The check costs nothing for the usual fastresume setup."""
    path = profile / "a.fastresume"
    write_fastresume("a.fastresume", dict(RELEVANT)).rename(path)
    cli_args("-b", str(profile), "-e", "/some/test", "-n", "/new", "-z")

    assert main() is None
    assert FastResume(path).save_path == "/new/path"
