"""`-m/--map EXISTING NEW`, repeatable: several roots in one run.

Moving more than one share or drive used to mean one run per root, each
taking its own backup zip. Every path value is rewritten by the first mapping
that matches it, once, so mappings never feed into each other.
"""

import pytest

from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.cli import (
    main,
    parse_args,
    resolve_mappings,
    resolve_target_os,
)
from qbt_migrate.enums import TargetOS
from qbt_migrate.methods import first_match, map_path


MOVIES = {
    "save_path": "/data/movies/A",
    "qBt-savePath": "/data/movies/A",
    "qBt-downloadPath": "/data/incomplete/A",
    "mapped_files": ["/data/movies/A/a.mkv", "/data/tv/A/b.mkv"],
}
TV = {"save_path": "/data/tv/B", "qBt-savePath": "/data/tv/B"}
OTHER = {"save_path": "/elsewhere/C", "qBt-savePath": "/elsewhere/C"}

TWO_MAPS = (
    "-m",
    "/data/movies",
    "/srv/media/movies",
    "-m",
    "/data/tv",
    "/srv/media/tv",
)


def library(write_fastresume):
    write_fastresume("movies.fastresume", dict(MOVIES))
    write_fastresume("tv.fastresume", dict(TV))
    write_fastresume("other.fastresume", dict(OTHER))


def test_map_is_repeatable_and_paired():
    """Each -m keeps its two halves together, in the order given."""
    args = parse_args(list(TWO_MAPS))
    assert args.mappings == [
        ["/data/movies", "/srv/media/movies"],
        ["/data/tv", "/srv/media/tv"],
    ]
    assert args.existing_path is None


def test_map_with_one_value_is_an_argparse_error(capsys):
    """A lone EXISTING is caught by argparse itself, exit 2."""
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["-m", "/data/movies"])
    assert exit_info.value.code == 2
    assert "expected 2 arguments" in capsys.readouterr().err


def test_several_roots_in_one_run(write_fastresume, temp_dir, cli_args):
    """Every key and mapped_files entry picks its own mapping."""
    library(write_fastresume)
    cli_args("-b", str(temp_dir), *TWO_MAPS)

    assert main() is None

    movies = FastResume(temp_dir / "movies.fastresume")
    assert movies.save_path == "/srv/media/movies/A"
    assert movies.qbt_save_path == "/srv/media/movies/A"
    # Neither mapping matches it, so it is left alone.
    assert movies.qbt_download_path == "/data/incomplete/A"
    # Each entry picks its own mapping.
    assert movies.mapped_files == [
        "/srv/media/movies/A/a.mkv",
        "/srv/media/tv/A/b.mkv",
    ]
    assert FastResume(temp_dir / "tv.fastresume").save_path == (
        "/srv/media/tv/B"
    )
    assert FastResume(temp_dir / "other.fastresume").save_path == (
        "/elsewhere/C"
    )


def test_backup_taken_once_per_run(write_fastresume, temp_dir, cli_args):
    """One zip for the whole run, not one per mapping."""
    library(write_fastresume)
    cli_args("-b", str(temp_dir), *TWO_MAPS)

    assert main() is None
    assert len(list(temp_dir.glob("fastresume_backup*.zip"))) == 1


def test_file_matching_only_a_later_mapping_is_discovered(
    write_fastresume, temp_dir
):
    """Discovery looks at every existing path, not only the first."""
    write_fastresume("tv.fastresume", dict(TV))
    found = list(
        QBTBatchMove.discover_relevant_fast_resume(
            temp_dir, "/data/movies", extra_paths=["/data/tv"]
        )
    )
    assert [f.file_path.name for f in found] == ["tv.fastresume"]


def test_first_matching_mapping_wins(write_fastresume, temp_dir, cli_args):
    """Order is precedence: the earlier, narrower root is used."""
    write_fastresume("tv.fastresume", dict(TV))
    cli_args(
        "-b",
        str(temp_dir),
        "-m",
        "/data/tv",
        "/first",
        "-m",
        "/data",
        "/second",
    )

    assert main() is None
    assert FastResume(temp_dir / "tv.fastresume").save_path == "/first/B"


def test_mappings_never_chain(write_fastresume, temp_dir, cli_args):
    """`/a -> /b` then `/b -> /c` must not turn `/a` into `/c`."""
    write_fastresume("a.fastresume", {"save_path": "/a/x"})
    write_fastresume("b.fastresume", {"save_path": "/b/y"})
    cli_args("-b", str(temp_dir), "-m", "/a", "/b", "-m", "/b", "/c")

    assert main() is None
    assert FastResume(temp_dir / "a.fastresume").save_path == "/b/x"
    assert FastResume(temp_dir / "b.fastresume").save_path == "/c/y"


def test_existing_and_new_path_are_the_first_mapping(
    write_fastresume, temp_dir, cli_args
):
    """-e/-n combined with -m is tried before any -m."""
    write_fastresume("tv.fastresume", dict(TV))
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data/tv",
        "-n",
        "/from-e",
        "-m",
        "/data",
        "/from-m",
    )

    assert main() is None
    assert FastResume(temp_dir / "tv.fastresume").save_path == "/from-e/B"


@pytest.mark.parametrize("half", [("-e", "/data"), ("-n", "/mnt")])
def test_half_a_pair_with_map_is_rejected(temp_dir, cli_args, caplog, half):
    cli_args("-b", str(temp_dir), *half, *TWO_MAPS)
    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2
    assert "give both or neither" in caplog.text


def test_empty_map_value_is_rejected(temp_dir, cli_args, caplog):
    """An empty EXISTING would match every path."""
    cli_args("-b", str(temp_dir), "-m", "/data", "/mnt", "-m", "", "/x")
    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2
    assert "non-empty EXISTING and NEW" in caplog.text


def test_map_alone_does_not_prompt_for_paths(
    monkeypatch, write_fastresume, temp_dir, cli_args, interactive_stdin
):
    """Only the path prompts are skipped; -r/-t prompts behave as before."""
    asked = []

    def answer(message):
        asked.append(message)
        return ""

    monkeypatch.setattr("builtins.input", answer)
    write_fastresume("tv.fastresume", dict(TV))
    cli_args("-b", str(temp_dir), *TWO_MAPS)

    assert main() is None
    assert not any("Path:" in message for message in asked)
    assert FastResume(temp_dir / "tv.fastresume").save_path == (
        "/srv/media/tv/B"
    )


def test_regex_applies_to_every_mapping(write_fastresume, temp_dir, cli_args):
    """-r turns every -m into a pattern, capture groups included."""
    library(write_fastresume)
    cli_args(
        "-b",
        str(temp_dir),
        "-r",
        # Regex escapes contain backslashes, which auto-detect on master
        # reads as Windows; that is a separate change.
        "-t",
        "Linux",
        "-m",
        r"^/data/movies/(\w+)",
        r"/films/\1",
        "-m",
        r"^/data/tv/(\w+)",
        r"/series/\1",
    )

    assert main() is None
    movies = FastResume(temp_dir / "movies.fastresume")
    assert movies.save_path == "/films/A"
    assert movies.mapped_files == ["/films/A/a.mkv", "/series/A/b.mkv"]
    assert FastResume(temp_dir / "tv.fastresume").save_path == "/series/B"


def test_regex_mappings_never_chain(write_fastresume, temp_dir):
    """The no-chaining rule holds in regex mode too."""
    path = write_fastresume("a.fastresume", {"save_path": "/a/x"})
    fast_resume = FastResume(path)
    fast_resume.replace_paths(
        "^/a",
        "/b",
        regex_path=True,
        save_file=False,
        create_backup=False,
        extra_mappings=[("^/b", "/c")],
    )
    assert fast_resume.save_path == "/b/x"


def test_target_os_detected_over_all_mappings(
    write_fastresume, temp_dir, cli_args
):
    """A pair that says nothing about the OS does not veto one that does."""
    write_fastresume(
        "d.fastresume", {"save_path": "D:\\Movies\\A\\", "qBt-savePath": ""}
    )
    write_fastresume(
        "e.fastresume", {"save_path": "E:\\TV\\B\\", "qBt-savePath": ""}
    )
    # The first pair says nothing about the OS; the second one does.
    cli_args(
        "-b",
        str(temp_dir),
        "-m",
        "D:\\Movies",
        "/srv/media/movies",
        "-m",
        "E:",
        "/srv/media/tv",
    )

    assert main() is None
    assert FastResume(temp_dir / "d.fastresume").save_path == (
        "/srv/media/movies/A/"
    )
    assert FastResume(temp_dir / "e.fastresume").save_path == (
        "/srv/media/tv/TV/B/"
    )


def test_conflicting_target_os_requires_t(temp_dir, cli_args, caplog):
    """Windows-bound and Linux-bound pairs cannot share one conversion."""
    cli_args(
        "-b",
        str(temp_dir),
        "-m",
        "D:\\Movies",
        "/mnt/movies",
        "-m",
        "/data/tv",
        "E:\\TV",
    )
    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2
    assert "-t/--target-os" in caplog.text


def test_explicit_target_os_settles_a_conflict():
    assert (
        resolve_target_os(
            "Linux", "D:\\Movies", "/mnt", [("/data/tv", "E:\\TV")]
        )
        is TargetOS.POSIX
    )


def test_dry_run_names_the_mapping_per_key(
    write_fastresume, temp_dir, cli_args, caplog
):
    """Dry run numbers the mappings and tags each change with one."""
    library(write_fastresume)
    cli_args("-b", str(temp_dir), "-d", *TWO_MAPS)

    with caplog.at_level("INFO", logger="qbt_migrate"):
        assert main() is None

    text = caplog.text
    assert "Mappings, first match wins:" in text
    assert "1: '/data/movies' -> '/srv/media/movies'" in text
    assert "2: '/data/tv' -> '/srv/media/tv'" in text
    assert "'/data/tv/B' -> '/srv/media/tv/B'  (mapping 2)" in text
    assert "'/data/movies/A' -> '/srv/media/movies/A'  (mapping 1)" in text
    assert "path /data/movies, /data/tv ..." in text
    # Nothing written.
    assert FastResume(temp_dir / "tv.fastresume").save_path == "/data/tv/B"


def test_plan_marks_separator_only_changes_without_a_mapping(
    write_fastresume,
):
    path = write_fastresume(
        "d.fastresume",
        {"save_path": "D:\\Movies\\A", "qBt-downloadPath": "F:\\tmp"},
    )
    plan = FastResume(path).plan_paths(
        "D:\\Movies",
        "/movies",
        target_os=TargetOS.POSIX,
        extra_mappings=[("E:\\TV", "/tv")],
    )
    mappings = {change.key: change.mappings for change in plan.changes}
    assert mappings["save_path"] == (0,)
    assert mappings["qBt-downloadPath"] == ()


def test_single_pair_dry_run_is_unchanged(
    write_fastresume, temp_dir, cli_args, caplog
):
    """No mapping numbers in output when -m is not used."""
    write_fastresume("tv.fastresume", dict(TV))
    cli_args("-b", str(temp_dir), "-d", "-e", "/data/tv", "-n", "/tv")

    with caplog.at_level("INFO", logger="qbt_migrate"):
        assert main() is None

    assert "'/data/tv/B' -> '/tv/B'" in caplog.text
    assert "(mapping" not in caplog.text
    assert "Mappings, first match wins" not in caplog.text


def test_single_pair_plan_has_no_mapping_index(write_fastresume):
    path = write_fastresume("tv.fastresume", dict(TV))
    plan = FastResume(path).plan_paths("/data/tv", "/tv")
    assert all(change.mappings == () for change in plan.changes)


def test_map_path_with_one_mapping_matches_replace_path():
    """One mapping behaves exactly like master did."""
    assert map_path("/a/x", [("/a", "/b")]) == "/b/x"
    assert map_path("/z/x", [("/a", "/b")]) == "/z/x"
    assert map_path("/a/x", [("^/a", "/b")], regex_path=True) == "/b/x"


def test_first_match_returns_none_without_a_match():
    assert first_match("/z", ["/a", "/b"]) is None
    assert first_match("/b/x", ["/a", "/b"]) == 1
    assert first_match("/b/x", ["^/a", "^/b"], regex_path=True) == 1


def run_main():
    """`main()`'s exit code, whether argparse or `main` itself refuses."""
    try:
        return main()
    except SystemExit as e:
        return e.code


@pytest.mark.parametrize(
    "argv",
    [
        ("-m", "/data/movies", "-d"),
        ("-m", "/data/movies", "-r"),
        ("-d", "-m", "/data/movies", "-z"),
        ("-m", "-d", "/data/movies"),
    ],
)
def test_option_like_map_value_is_rejected(
    write_fastresume, temp_dir, cli_args, argv
):
    """A forgotten NEW must not swallow the next flag and write anyway.

    Python 3.12+ argparse hands `-d` over as NEW; 3.10 and 3.11 refuse it.
    Either way the run stops with exit 2 and nothing is written.
    """
    library(write_fastresume)
    cli_args("-b", str(temp_dir), *argv)

    assert run_main() == 2
    assert FastResume(temp_dir / "movies.fastresume").save_path == (
        "/data/movies/A"
    )
    assert not list(temp_dir.glob("fastresume_backup*.zip"))


def test_option_like_value_message_names_it():
    """Checked on the parsed values, so it holds on every Python version."""
    args = parse_args([])
    args.mappings = [["/data/movies", "-d"]]
    assert "'-d' looks like an option" in resolve_mappings(args)


@pytest.mark.parametrize(
    "argv, later, earlier",
    [
        (("-m", "/data", "/x", "-m", "/data/movies", "/y"), 2, 1),
        (("-m", "/data", "/x", "-m", "/data", "/y"), 2, 1),
        (("-e", "/data", "-n", "/x", "-m", "/data/tv", "/y"), 2, 1),
        (("-m", "/a", "/b", "-m", "D:\\", "/c", "-m", "D:/x", "/d"), 3, 2),
    ],
)
def test_unreachable_mapping_is_rejected(
    write_fastresume, temp_dir, cli_args, caplog, argv, later, earlier
):
    """A mapping shadowed by an earlier, broader one stops the run."""
    library(write_fastresume)
    cli_args("-b", str(temp_dir), *argv)

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2
    assert f"Mapping {later} " in caplog.text
    assert f"mapping {earlier} " in caplog.text
    assert "narrower root first" in caplog.text
    assert not list(temp_dir.glob("fastresume_backup*.zip"))


def test_shadowing_is_not_checked_for_regex(
    write_fastresume, temp_dir, cli_args
):
    """Patterns cannot be compared cheaply, so regex runs go ahead."""
    library(write_fastresume)
    cli_args(
        "-b", str(temp_dir), "-r", "-m", "/data", "/x", "-m", "/data/tv", "/y"
    )

    assert main() is None
    assert FastResume(temp_dir / "tv.fastresume").save_path == "/x/tv/B"


def test_dry_run_tags_every_mapping_a_list_used(
    write_fastresume, temp_dir, cli_args, caplog
):
    """mapped_files entries can use different mappings; all are named."""
    library(write_fastresume)
    cli_args("-b", str(temp_dir), "-d", *TWO_MAPS)

    with caplog.at_level("INFO", logger="qbt_migrate"):
        assert main() is None

    assert "2 of 2 entries" in caplog.text
    assert "'/srv/media/movies/A/a.mkv'  (mappings 1, 2)" in caplog.text
