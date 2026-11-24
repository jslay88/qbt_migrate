"""`--downgrade-resume`: libtorrent 2.1 resume data to the 1.2 format.

libtorrent 1.2 reads `pieces` as one byte per piece. libtorrent 2.1 writes it
as a packed bitfield with a `file-version` of 2, which 1.2 does not check, so
going back to a qBittorrent lt12 build rechecks every torrent. The bit order
and the expected values below come from libtorrent's own test of the version 2
reader, `v2_pieces_field` in test/test_read_resume.cpp (RC_2_0).
"""

import zipfile

import bencodepy
import pytest

from qbt_migrate.cli import main
from qbt_migrate.downgrade import (
    downgrade_data,
    downgrade_resume,
    piece_count,
    plan_file,
    to_ascii_bits,
    unpack_bits,
)
from qbt_migrate.exceptions import FastResumeUpdateError
from qbt_migrate.process import Process


raw = bencodepy.Bencode()

# libtorrent's vector: have pieces 5, 7, 8, 9 and verified 0, 1, 5, 6, 8 of 10.
V2_PIECES = b"\x05\xc0"
V2_VERIFIED = b"\xc6\x80"
# The same state, one byte per piece: bit 0 have, bit 1 verified.
V1_PIECES = b"\x02\x02\x00\x00\x00\x03\x02\x01\x03\x01"
TEN_PIECES = b"h" * 200

V2 = {
    "file-format": "libtorrent resume file",
    "file-version": 2,
    "info-hash": b"\x11" * 20,
    "info-hash2": b"\x22" * 32,
    "libtorrent-version": "2.1.3.0",
    "pieces": V2_PIECES,
    "verified": V2_VERIFIED,
    "save_path": "/data/x",
    "unfinished": [{"piece": 2, "bitmask": b"\xf0\x0f"}],
    "qBt-tags": ["a"],
}


@pytest.fixture
def write_torrent(temp_dir):
    def _write(stem: str, info: object) -> None:
        (temp_dir / f"{stem}.torrent").write_bytes(raw.encode({"info": info}))

    return _write


@pytest.fixture
def v2_file(write_fastresume, write_torrent):
    """A version 2 resume file with its ten piece `.torrent` beside it."""

    def _make(stem: str = "a", **changes: object):
        data = {**V2, **changes}
        write_torrent(stem, {"name": "x", "pieces": TEN_PIECES})
        return write_fastresume(f"{stem}.fastresume", data)

    return _make


def read(path):
    return raw.decode(path.read_bytes())


def test_bits_are_most_significant_first():
    """libtorrent's vector decodes to its own expected bits, MSB first."""

    have = unpack_bits(V2_PIECES, 10)
    verified = unpack_bits(V2_VERIFIED, 10)
    assert [i for i, bit in enumerate(have) if bit] == [5, 7, 8, 9]
    assert [i for i, bit in enumerate(verified) if bit] == [0, 1, 5, 6, 8]


def test_converts_libtorrents_own_vector(v2_file, temp_dir):
    """The vector becomes one byte per piece, have | verified << 1."""

    path = v2_file()

    downgrade_resume(temp_dir, create_backup=False)

    data = read(path)
    assert data[b"pieces"] == V1_PIECES
    assert data[b"file-version"] == 1
    assert b"verified" not in data


def test_padding_bits_are_trimmed(v2_file, temp_dir):
    """Ten pieces take two packed bytes. Bits 10 to 15 are padding."""
    path = v2_file(pieces=b"\xff\xff", verified=b"")

    downgrade_resume(temp_dir, create_backup=False)

    assert read(path)[b"pieces"] == b"\x01" * 10


def test_everything_else_is_kept_byte_for_byte(v2_file, temp_dir):
    """Only the three keys that differ between versions change."""

    path = v2_file()
    before = read(path)

    downgrade_resume(temp_dir, create_backup=False)

    after = read(path)
    keys = before.keys() | after.keys()
    changed = {k for k in keys if before.get(k) != after.get(k)}
    assert changed == {b"pieces", b"verified", b"file-version"}
    # Packed in both versions, so it must not be touched.
    assert after[b"unfinished"] == [{b"piece": 2, b"bitmask": b"\xf0\x0f"}]
    assert after[b"info-hash2"] == b"\x22" * 32


def test_verified_without_pieces(v2_file, temp_dir):
    """A verified field alone still yields bit 1 with no have bits."""

    path = v2_file()
    data = read(path)
    del data[b"pieces"]
    path.write_bytes(raw.encode(data))

    downgrade_resume(temp_dir, create_backup=False)

    assert read(path)[b"pieces"] == b"\x02\x02\x00\x00\x00\x02\x02\x00\x02\x00"


def test_trees_become_ascii_bits():
    """Version 1 stores the merkle bitfields as `0`/`1` characters."""
    data = {
        b"file-version": 2,
        b"trees": [
            {b"hashes": b"h" * 32, b"verified": b"\xa0", b"mask": b"\x80"},
            {b"hashes": b"h" * 32},
            b"not a dict",
        ],
    }

    trees = downgrade_data(data, lambda: pytest.fail("not needed"))[b"trees"]

    assert trees[0][b"verified"] == b"10100000"
    assert trees[0][b"mask"] == b"10000000"
    assert trees[1] == {b"hashes": b"h" * 32}
    assert trees[2] == b"not a dict"
    # The input is not modified.
    assert data[b"trees"][0][b"verified"] == b"\xa0"


def test_trees_that_are_not_a_list_are_left_alone():
    """Unexpected trees content is passed through, not guessed at."""

    data = {b"file-version": 2, b"trees": b"odd"}
    assert downgrade_data(data, lambda: 0)[b"trees"] == b"odd"


def test_to_ascii_bits():
    """Tree bitfields expand to ASCII, padding bits included."""

    assert to_ascii_bits(b"\x01\x80") == b"0000000110000000"


def test_magnet_without_metadata_needs_no_piece_count(
    write_fastresume, temp_dir
):
    """No bitfield means no piece count is needed to convert."""

    data = {k: v for k, v in V2.items() if k not in ("pieces", "verified")}
    path = write_fastresume("m.fastresume", data)

    downgrade_resume(temp_dir, create_backup=False)

    assert read(path)[b"file-version"] == 1


def test_piece_count_from_info_in_resume_data(write_fastresume, temp_dir):
    """Without a .torrent, the info dict in the resume data is used."""

    path = write_fastresume(
        "m.fastresume", {**V2, "info": {"name": "x", "pieces": TEN_PIECES}}
    )

    downgrade_resume(temp_dir, create_backup=False)

    assert read(path)[b"pieces"] == V1_PIECES


def test_missing_torrent_is_skipped(write_fastresume, temp_dir, caplog):
    """No metadata anywhere: the file is left alone with a warning."""

    path = write_fastresume("m.fastresume", dict(V2))
    before = path.read_bytes()

    with caplog.at_level("WARNING", logger="qbt_migrate.downgrade"):
        summary = downgrade_resume(temp_dir, create_backup=False)

    assert path.read_bytes() == before
    assert summary.skipped[0][0] == path
    assert "no m.torrent and no info" in caplog.text


def test_v2_only_torrent_is_skipped(write_fastresume, write_torrent, temp_dir):
    """No v1 piece hashes: libtorrent 1.2 cannot load it, so skip."""

    path = write_fastresume("a.fastresume", dict(V2))
    write_torrent("a", {"name": "x", "meta version": 2, "file tree": {}})
    before = path.read_bytes()

    summary = downgrade_resume(temp_dir, create_backup=False)

    assert path.read_bytes() == before
    assert "v2-only torrent" in summary.skipped[0][1]


def test_unknown_version_is_skipped(v2_file, temp_dir):
    """A file-version this tool does not know is left alone."""

    path = v2_file(**{"file-version": 3})
    before = path.read_bytes()

    summary = downgrade_resume(temp_dir, create_backup=False)

    assert path.read_bytes() == before
    assert "unknown file-version 3" in summary.skipped[0][1]


@pytest.mark.parametrize("version", [1, None])
def test_version_1_is_untouched(write_fastresume, temp_dir, version):
    """Version 1 (or no version) is not rewritten at all."""

    data = {**V2, "file-version": version, "pieces": b"\x01" * 10}
    if version is None:
        del data["file-version"]
    path = write_fastresume("a.fastresume", data)
    before = path.read_bytes()

    summary = downgrade_resume(temp_dir, create_backup=False)

    assert path.read_bytes() == before
    assert summary.discovered == 1
    assert summary.changing == []


def test_second_run_changes_nothing(v2_file, temp_dir):
    """Converting is idempotent."""

    path = v2_file()
    downgrade_resume(temp_dir, create_backup=False)
    once = path.read_bytes()

    summary = downgrade_resume(temp_dir, create_backup=False)

    assert path.read_bytes() == once
    assert summary.changing == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"pieces": b"\x05\xc0\x00"}, "pieces is 3 bytes, but 10 pieces"),
        ({"verified": b"\x00"}, "verified is 1 bytes, but 10 pieces"),
        ({"pieces": 5}, "pieces is not a byte string"),
    ],
)
def test_bitfield_that_does_not_fit_fails(v2_file, temp_dir, changes, message):
    """A bitfield that does not fit the torrent fails, unwritten."""

    path = v2_file(**changes)
    before = path.read_bytes()

    with pytest.raises(FastResumeUpdateError) as excinfo:
        downgrade_resume(temp_dir, create_backup=False)

    assert message in str(excinfo.value.failures[path])
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (b"le", "has no info dictionary"),
        ({"info": b"x"}, "has no info dictionary"),
        ({"info": {"pieces": b"short"}}, "malformed info.pieces"),
        ({"info": {"pieces": 7}}, "malformed info.pieces"),
    ],
)
def test_bad_torrent_fails(write_fastresume, temp_dir, metadata, message):
    """A .torrent that is not a valid v1 torrent is an error."""

    path = write_fastresume("a.fastresume", dict(V2))
    torrent = temp_dir / "a.torrent"
    torrent.write_bytes(
        metadata if isinstance(metadata, bytes) else raw.encode(metadata)
    )

    with pytest.raises(ValueError, match=message):
        piece_count(path, read(path))


def test_good_files_still_convert_when_one_fails(v2_file, temp_dir):
    """One failure does not stop the rest of the batch."""

    bad = v2_file("a", pieces=b"\x00")
    good = v2_file("b")

    with pytest.raises(FastResumeUpdateError) as excinfo:
        downgrade_resume(temp_dir, create_backup=False)

    assert list(excinfo.value.failures) == [bad]
    assert read(good)[b"file-version"] == 1


def test_dry_run_writes_nothing_and_reports_changes(v2_file, temp_dir):
    """The dry run reports every changed key and writes nothing."""

    path = v2_file()
    before = path.read_bytes()

    summary = downgrade_resume(temp_dir, write=False)

    assert path.read_bytes() == before
    assert list(temp_dir.glob("*.zip")) == []
    changes = {c.key: (c.old, c.new) for c in summary.plans[0].changes}
    assert changes == {
        "file-version": ("2", "1"),
        "pieces": ("2 bytes", "10 bytes"),
        "verified": ("2 bytes", "absent"),
    }


def test_dry_run_lists_trees(write_fastresume, temp_dir):
    """Converted trees show up in the plan too."""

    for files, label in ((1, "1 file"), (2, "2 files")):
        path = write_fastresume(
            "m.fastresume",
            {"file-version": 2, "trees": [{"verified": b"\x80"}] * files},
        )
        plan, _ = plan_file(path, read(path))
        assert ("trees", "packed", f"ASCII 0/1, {label}") in {
            (c.key, c.old, c.new) for c in plan.changes
        }


def test_dry_run_reports_failures_instead_of_raising(v2_file, temp_dir):
    """Dry run failures are listed, not raised."""

    path = v2_file(pieces=b"\x00")

    summary = downgrade_resume(temp_dir, write=False)

    assert summary.failing[0].file_path == path


def test_unreadable_file_stops_before_anything_is_written(
    v2_file, write_fastresume, temp_dir
):
    """An unreadable file aborts before any write or backup."""

    good = v2_file("b")
    before = good.read_bytes()
    (temp_dir / "a.fastresume").write_bytes(b"not bencode")

    with pytest.raises(bencodepy.exceptions.BencodeDecodeError):
        downgrade_resume(temp_dir)

    assert good.read_bytes() == before
    assert list(temp_dir.glob("*.zip")) == []


@pytest.mark.parametrize("content", [b"not bencode", b"le"])
def test_unreadable_files_can_be_skipped(v2_file, temp_dir, content):
    """With skip_bad_files, unreadable files are skipped."""

    good = v2_file("b")
    (temp_dir / "a.fastresume").write_bytes(content)

    summary = downgrade_resume(
        temp_dir, create_backup=False, skip_bad_files=True
    )

    assert summary.discovered == 1
    assert read(good)[b"file-version"] == 1


def test_not_a_directory(temp_dir):
    """A missing BT_backup path is reported as such."""

    with pytest.raises(NotADirectoryError):
        downgrade_resume(temp_dir / "missing")


def test_backup_is_taken_before_writing(v2_file, temp_dir):
    """The backup zip holds the original bytes and the .torrent."""

    path = v2_file()
    before = path.read_bytes()

    downgrade_resume(temp_dir)

    (archive,) = temp_dir.glob("fastresume_backup*.zip")
    with zipfile.ZipFile(archive) as z:
        assert z.read("a.fastresume") == before
        assert "a.torrent" in z.namelist()


# CLI


def test_cli_needs_no_paths(v2_file, temp_dir, cli_args, caplog):
    """--downgrade-resume runs without -e/-n and makes a backup."""

    path = v2_file()
    cli_args("-b", str(temp_dir), "--downgrade-resume")

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        assert main() is None

    assert read(path)[b"pieces"] == V1_PIECES
    assert len(list(temp_dir.glob("fastresume_backup*.zip"))) == 1
    assert (
        "Converted 1 of 1 fastresume file to the libtorrent 1.2 format."
        in caplog.text
    )


def test_cli_dry_run(v2_file, write_fastresume, temp_dir, cli_args, caplog):
    """-d lists changes, failures and every count, writing nothing."""

    path = v2_file("a")
    before = path.read_bytes()
    v2_file("b", pieces=b"\x00")
    write_fastresume("c.fastresume", {"file-version": 1})
    write_fastresume("d.fastresume", dict(V2))
    cli_args("-b", str(temp_dir), "--downgrade-resume", "-d")

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        assert main() is None

    assert path.read_bytes() == before
    assert "pieces            '2 bytes' -> '10 bytes'" in caplog.text
    assert "would fail: pieces is 1 bytes" in caplog.text
    assert (
        "Would convert 1 of 4 fastresume files to the libtorrent 1.2 format, "
        "1 already in it, 1 left as they are, 1 would fail. "
        "Nothing was written." in caplog.text
    )


def test_cli_nothing_to_convert(temp_dir, cli_args, caplog):
    """An empty BT_backup is a clean no-op."""

    cli_args("-b", str(temp_dir), "--downgrade-resume", "-d")
    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        assert main() is None
    assert "Would convert 0 of 0 fastresume files" in caplog.text


def test_cli_skip_backup(v2_file, temp_dir, cli_args, caplog):
    """-z skips the archive and says so."""

    v2_file()
    cli_args("-b", str(temp_dir), "--downgrade-resume", "-z")

    with caplog.at_level("WARNING", logger="qbt_migrate.cli"):
        assert main() is None

    assert list(temp_dir.glob("*.zip")) == []
    assert "Skipping the backup archive" in caplog.text


@pytest.mark.parametrize(
    "extra", [["-e", "/a"], ["-n", "/b"], ["-r"], ["-t", "Linux"]]
)
def test_cli_refuses_path_options(v2_file, temp_dir, cli_args, extra):
    """Path options are rejected in this mode, exit 2."""

    path = v2_file()
    before = path.read_bytes()
    cli_args("-b", str(temp_dir), "--downgrade-resume", *extra)

    assert main() == 2
    assert path.read_bytes() == before


def test_cli_refuses_while_qbittorrent_runs(
    v2_file, temp_dir, cli_args, monkeypatch
):
    """The running-client preflight applies here too, exit 2."""

    monkeypatch.setattr(
        "qbt_migrate.cli.find_processes",
        lambda: [Process(4242, "qbittorrent")],
    )
    path = v2_file()
    before = path.read_bytes()
    cli_args("-b", str(temp_dir), "--downgrade-resume")

    assert main() == 2
    assert path.read_bytes() == before


def test_cli_bad_file(temp_dir, cli_args, caplog):
    """An unreadable file exits 1."""

    (temp_dir / "a.fastresume").write_bytes(b"not bencode")
    cli_args("-b", str(temp_dir), "--downgrade-resume")
    assert main() == 1


def test_cli_bad_backup_path(temp_dir, cli_args):
    """A missing BT_backup path exits 2."""

    cli_args("-b", str(temp_dir / "missing"), "--downgrade-resume")
    assert main() == 2


def test_cli_failed_conversion(v2_file, temp_dir, cli_args, caplog):
    """A failed conversion exits 1 with a message."""

    v2_file(pieces=b"\x00")
    cli_args("-b", str(temp_dir), "--downgrade-resume", "-z")

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 1

    assert "1 file(s) were not converted" in caplog.text


def test_write_failure_is_reported(v2_file, temp_dir, monkeypatch):
    """A failing write is reported and leaves the file as it was."""

    path = v2_file()
    before = path.read_bytes()

    class Unencodable(bencodepy.Bencode):
        def encode(self, data):
            raise OSError("[Errno 28] No space left on device")

    monkeypatch.setattr("qbt_migrate.downgrade.raw_bencode", Unencodable())

    with pytest.raises(FastResumeUpdateError) as excinfo:
        downgrade_resume(temp_dir, create_backup=False)

    assert isinstance(excinfo.value.failures[path], OSError)
    assert path.read_bytes() == before


def test_no_backup_when_nothing_changes(v2_file, temp_dir):
    """The archive name has one-second resolution. A no-op rerun must not
    replace the archive of the originals with already converted files."""
    v2_file()
    downgrade_resume(temp_dir)
    (archive,) = temp_dir.glob("fastresume_backup*.zip")
    original = archive.read_bytes()

    downgrade_resume(temp_dir)

    assert list(temp_dir.glob("fastresume_backup*.zip")) == [archive]
    assert archive.read_bytes() == original


@pytest.mark.parametrize("dry_run", [[], ["-d"]])
def test_cli_refuses_sqlite_storage(
    v2_file, temp_dir, cli_args, caplog, dry_run
):
    """With torrents.db beside BT_backup nothing is converted, dry run too."""
    bt_backup = temp_dir / "BT_backup"
    bt_backup.mkdir()
    (temp_dir / "torrents.db").write_bytes(b"SQLite format 3\x00")
    path = v2_file()
    target = bt_backup / path.name
    path.rename(target)
    before = target.read_bytes()
    cli_args("-b", str(bt_backup), "--downgrade-resume", *dry_run)

    with caplog.at_level("ERROR", logger="qbt_migrate.cli"):
        assert main() == 2

    assert target.read_bytes() == before
    assert list(bt_backup.glob("*.zip")) == []
    assert "torrents.db" in caplog.text
    assert "While still on the libtorrent 2.1 build" in caplog.text


def test_torrents_db_directory_is_not_sqlite_storage(
    v2_file, temp_dir, cli_args
):
    """Only a file named torrents.db counts, as in qBittorrent."""
    bt_backup = temp_dir / "BT_backup"
    bt_backup.mkdir()
    (temp_dir / "torrents.db").mkdir()
    path = v2_file()
    target = bt_backup / path.name
    path.rename(target)
    (temp_dir / "a.torrent").rename(bt_backup / "a.torrent")
    cli_args("-b", str(bt_backup), "--downgrade-resume", "-z")

    assert main() is None
    assert read(target)[b"file-version"] == 1


def test_sqlite_check_works_from_inside_bt_backup(
    v2_file, temp_dir, cli_args, monkeypatch
):
    """`-b .` run from inside BT_backup still finds torrents.db above it."""
    bt_backup = temp_dir / "BT_backup"
    bt_backup.mkdir()
    (temp_dir / "torrents.db").write_bytes(b"SQLite format 3\x00")
    path = v2_file()
    target = bt_backup / path.name
    path.rename(target)
    before = target.read_bytes()
    monkeypatch.chdir(bt_backup)
    cli_args("-b", ".", "--downgrade-resume")

    assert main() == 2
    assert target.read_bytes() == before
