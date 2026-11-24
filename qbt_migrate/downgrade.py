"""Convert libtorrent 2.1 resume data to the format libtorrent 1.2 reads.

libtorrent 2.1 writes `.fastresume` with `file-version` 2: `pieces` is a
packed bitfield (one bit per piece, most significant bit first) and the
verified pieces are a second packed bitfield under `verified`. libtorrent 1.2
never reads `file-version` and takes `pieces` as one byte per piece (bit 0
have, bit 1 verified), so it misreads a version 2 file and rechecks every
torrent. qBittorrent's lt12 builds therefore recheck the whole library after
running a default (lt 2.1) build once.

Version 1 is the format libtorrent 1.2 and 2.0 write, and 2.1 still reads it
(src/read_resume_data.cpp on RC_1_2 and RC_2_1), so a converted file loads
on all three. 2.1 writes version 2 again on its next save.

Only what differs between the versions is touched:

* `pieces`: packed bits become one byte per piece, `have | verified << 1`,
  trimmed to the real piece count (the packed form pads the last byte)
* `verified`: folded into `pieces` and removed. libtorrent 2.1 reads this key
  whatever the file version, so a leftover copy would override the bits just
  written into `pieces` if the user goes back to 2.1
* `trees[].verified` and `trees[].mask`: packed in version 2, a string of
  ASCII `0`/`1` in version 1. libtorrent 1.2 ignores `trees`; converting them
  keeps the merkle trees of hybrid torrents valid for 2.x
* `file-version`: 2 becomes 1

`unfinished[].bitmask` is packed in both versions and stays as it is. Every
other key, including `info-hash2`, is unknown to libtorrent 1.2, ignored by
it, and kept byte for byte so nothing is lost on the way back to 2.x.

The file is decoded without any string decoding: `pieces` of a seeded torrent
is all 0x01 bytes, which the package's UTF-8 decoder would hand back as `str`.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import bencodepy
from bencodepy.exceptions import BencodeDecodeError

from qbt_migrate.exceptions import FastResumeUpdateError
from qbt_migrate.methods import backup_folder
from qbt_migrate.names import torrent_name
from qbt_migrate.plans import MigrationPlan, PathChange, PlanSummary


logger = logging.getLogger(__name__)

# Bytes in, bytes out. Keys and values stay exactly as libtorrent wrote them.
raw_bencode = bencodepy.Bencode()

FILE_VERSION = b"file-version"
PIECES = b"pieces"
VERIFIED = b"verified"
TREES = b"trees"
TREE_BITFIELDS = (b"verified", b"mask")
INFO = b"info"
SHA1_LENGTH = 20


class SkipDowngrade(Exception):
    """This file cannot be converted, and is left as it is.

    Not a failure: nothing was attempted, and libtorrent 1.2 will recheck the
    torrent exactly as it would have without this tool.
    """


@dataclass
class DowngradeSummary(PlanSummary):
    """A `PlanSummary` plus the files left alone, with the reason why."""

    skipped: list[tuple[Path, str]] = field(default_factory=list)


def unpack_bits(packed: bytes, count: int) -> list[bool]:
    """The first `count` bits of a libtorrent bitfield, MSB first."""
    # Bit i lives in byte i // 8 under mask 0x80 >> (i % 8), the order the
    # RC_2_0 and RC_2_1 readers use (src/read_resume_data.cpp) and the one
    # libtorrent's v2_pieces_field test pins (test/test_read_resume.cpp).
    return [bool(packed[i >> 3] & (0x80 >> (i & 7))) for i in range(count)]


def to_ascii_bits(packed: bytes) -> bytes:
    """A packed bitfield as version 1 writes it: one `0`/`1` per bit."""
    # Every bit, padding included: RC_2_1 reads a version 2 tree bitfield as
    # len * 8 bits, so this keeps the same length when 2.x reads it back.
    return bytes(
        0x31 if bit else 0x30 for bit in unpack_bits(packed, len(packed) * 8)
    )


def _read_raw(path: Path) -> Any:
    return raw_bencode.decode(path.read_bytes())


def _pieces_in(info: Any, source: str) -> int:
    if not isinstance(info, dict):
        raise ValueError(f"{source} has no info dictionary")
    pieces = info.get(PIECES)
    # A v2-only torrent (BEP 52) has a per-file merkle "file tree" and no
    # SHA-1 list. libtorrent 1.2 has no v2 support, so it cannot load it.
    if pieces is None:
        raise SkipDowngrade(
            f"{source} has no v1 piece hashes (v2-only torrent). "
            f"libtorrent 1.2 cannot load it"
        )
    # info.pieces is the v1 SHA-1 of each piece concatenated (BEP 3).
    if not isinstance(pieces, bytes) or len(pieces) % SHA1_LENGTH:
        raise ValueError(f"{source} has a malformed info.pieces")
    return len(pieces) // SHA1_LENGTH


def piece_count(file_path: Path, data: dict[bytes, Any]) -> int:
    """Number of pieces, from the sibling `.torrent` or the resume data.

    qBittorrent moves the info dictionary out of the resume data into
    `<hash>.torrent`. A magnet that never got its metadata has neither, and
    then there are no pieces to convert either.

    :raises SkipDowngrade: No metadata, or a v2-only torrent.
    :raises ValueError: The metadata is not a torrent.
    """
    torrent = file_path.with_suffix(".torrent")
    # The .torrent first: qBittorrent moves the metadata there (names.py).
    if torrent.is_file():
        metadata = _read_raw(torrent)
        info = metadata.get(INFO) if isinstance(metadata, dict) else None
        return _pieces_in(info, torrent.name)
    if INFO in data:
        return _pieces_in(data[INFO], f"{file_path.name} (info)")
    raise SkipDowngrade(
        f"no {torrent.name} and no info in the resume data, so the piece "
        f"count is unknown"
    )


def _bitfield(data: dict[bytes, Any], key: bytes, count: int) -> list[bool]:
    packed = data.get(key, b"")
    if not isinstance(packed, bytes):
        raise ValueError(f"{key.decode()} is not a byte string")
    # libtorrent 2.1 writes exactly ceil(N / 8) bytes (to_string() in
    # src/write_resume_data.cpp, RC_2_1). Any other length means the
    # .torrent is not the one this data belongs to, and guessing which bits
    # are which would mark the wrong pieces as present.
    if packed and len(packed) != (count + 7) // 8:
        raise ValueError(
            f"{key.decode()} is {len(packed)} bytes, but {count} pieces "
            f"need {(count + 7) // 8}. Is {count} the right torrent?"
        )
    # unpack_bits stops at `count`, dropping the padding bits of the last
    # byte. Kept, they would become extra pieces past the end of the torrent.
    return unpack_bits(packed, count) if packed else [False] * count


def _downgrade_trees(trees: Any) -> Any:
    if not isinstance(trees, list):
        return trees
    converted = []
    for tree in trees:
        if isinstance(tree, dict):
            # Copied so the caller's data stays untouched for the dry run diff.
            tree = dict(tree)
            for key in TREE_BITFIELDS:
                if isinstance(tree.get(key), bytes):
                    tree[key] = to_ascii_bits(tree[key])
        converted.append(tree)
    return converted


def downgrade_data(
    data: dict[bytes, Any], count: Callable[[], int]
) -> dict[bytes, Any]:
    """Version 1 copy of version 2 resume data. `data` is not modified.

    `count` is called only when there is a piece bitfield to convert, so a
    magnet without metadata (and without pieces) needs no piece count.
    """
    result = dict(data)
    result[FILE_VERSION] = 1
    if TREES in result:
        result[TREES] = _downgrade_trees(result[TREES])
    if PIECES in data or VERIFIED in data:
        pieces = count()
        # Version 2 keeps "have" in pieces and "verified" (seed mode) in its
        # own key. Either may be missing: 2.1 omits verified when no bit is
        # set, and pieces when the bitfield is empty (src/write_resume_data
        # .cpp, RC_2_1).
        have = _bitfield(data, PIECES, pieces)
        verified = _bitfield(data, VERIFIED, pieces)
        # One byte per piece, bit 0 have and bit 1 verified: what RC_1_2's
        # read_resume_data.cpp tests with `& 1` and `& 2`. That reader sizes
        # the bitfield from the string length and never looks at
        # file-version, which is why a packed version 2 string gives it N / 8
        # pieces of garbage and a full recheck.
        result[PIECES] = bytes(
            h | (v << 1) for h, v in zip(have, verified, strict=True)
        )
        # RC_2_1 applies a top-level verified whatever the file-version, so a
        # stale copy would override the bits just written after a return to
        # 2.1. Its content is now in bit 1 of each byte.
        result.pop(VERIFIED, None)
    return result


def sqlite_resume_data(bt_backup_path: Path) -> Path | None:
    """qBittorrent's SQLite resume database next to BT_backup, if present.

    qBittorrent loads torrents from `torrents.db` whenever that file exists
    (`SessionImpl::prepareStartup`, src/base/bittorrent/sessionimpl.cpp):
    as its storage in SQLite mode, and once more to convert back after a
    switch to "Fastresume files". Either way the libtorrent 1.2 build would
    read the version 2 data in the database, not the converted files.
    """
    # Same rule as the SQLite check proposed for path migrations, so the two
    # can become one check when both are merged.
    # absolute() first: `-b .` run from inside BT_backup has '.' as its
    # parent, which would look for torrents.db in BT_backup itself.
    database = bt_backup_path.absolute().parent / "torrents.db"
    return database if database.is_file() else None


def describe(value: Any) -> str:
    """Short label for a raw value. Byte strings are not shown, only sized."""
    if value is None:
        return "absent"
    if isinstance(value, bytes):
        return f"{len(value)} bytes"
    # The only other key the conversion changes is file-version, an int.
    return str(value)


def diff_raw(
    file_path: Path, before: dict[bytes, Any], after: dict[bytes, Any]
) -> MigrationPlan:
    """Plan listing every key that differs between `before` and `after`."""
    changes = tuple(
        _change(key, before.get(key), new)
        for key in sorted(before.keys() | after.keys())
        if before.get(key) != (new := after.get(key))
    )
    return MigrationPlan(
        file_path=file_path,
        changes=changes,
        # Raw data has bytes keys, which torrent_name does not look up. It
        # still finds the name in the sibling .torrent, or uses the hash.
        name=torrent_name(file_path, {}),
    )


def _change(key: bytes, old: Any, new: Any) -> PathChange:
    # Sizes say nothing for trees: the list keeps its length and only the
    # encoding of the bitfields inside changes, so say that instead.
    # Only a list is ever rewritten (_downgrade_trees), so `new` is one.
    if key == TREES:
        files = f"{len(new)} file{'' if len(new) == 1 else 's'}"
        return PathChange(key.decode(), "packed", f"ASCII 0/1, {files}")
    return PathChange(key.decode(), describe(old), describe(new))


def iter_resume_data(
    bt_backup_path: Path, skip_bad_files: bool
) -> Iterator[tuple[Path, dict[bytes, Any]]]:
    """Every `.fastresume` in `bt_backup_path`, decoded, in name order.

    :raises BencodeDecodeError: A file is unreadable and not skipping.
    :raises ValueError: Likewise, for a file that is not a dictionary.
    """
    for path in sorted(bt_backup_path.glob("*.fastresume")):
        try:
            data = _read_raw(path)
            if not isinstance(data, dict):
                raise ValueError(f"{path} is not a bencoded dictionary")
        except (BencodeDecodeError, ValueError) as e:
            if not skip_bad_files:
                raise
            logger.warning(f"⚠️ Unable to parse {path}. Skipping!\n\n{e}")
            continue
        yield path, data


def plan_file(
    path: Path, data: dict[bytes, Any]
) -> tuple[MigrationPlan, dict[bytes, Any]]:
    """What converting this file does, and the converted data.

    The plan is empty, and the data unchanged, when already version 1.

    :raises SkipDowngrade: The file is left alone, see the message.
    :raises ValueError: The file cannot be converted.
    """
    # Missing means 1, the same default libtorrent's readers use.
    version = data.get(FILE_VERSION, 1)
    if version == 1:
        return MigrationPlan(file_path=path), data
    if version != 2:
        raise SkipDowngrade(f"unknown file-version {version!r}")
    after = downgrade_data(data, lambda: piece_count(path, data))
    return diff_raw(path, data, after), after


def plan_all(
    files: list[tuple[Path, dict[bytes, Any]]],
) -> tuple[DowngradeSummary, dict[Path, dict[bytes, Any]]]:
    """Plan every file. Returns the summary and the data to write per file."""
    summary = DowngradeSummary()
    converted: dict[Path, dict[bytes, Any]] = {}
    for path, data in files:
        try:
            plan, after = plan_file(path, data)
        except SkipDowngrade as e:
            logger.warning(f"⚠️ Leaving {path.name} as it is: {e}")
            summary.skipped.append((path, str(e)))
            continue
        except Exception as e:  # noqa: BLE001
            logger.error(f"🛑 Cannot convert {path.name}: {e}")
            plan = MigrationPlan(file_path=path, error=str(e))
        if plan:
            converted[path] = after
        summary.plans.append(plan)
    return summary, converted


def write_all(
    converted: dict[Path, dict[bytes, Any]],
) -> dict[Path, BaseException]:
    """Write each converted file. Returns the ones that failed."""
    failures: dict[Path, BaseException] = {}
    for path, data in converted.items():
        try:
            # Encoded before the file is opened, so a value that cannot be
            # encoded never truncates it.
            path.write_bytes(raw_bencode.encode(data))
        except Exception as e:  # noqa: BLE001
            logger.error(f"🛑 Failed to write {path.name}: {e}")
            failures[path] = e
    return failures


def downgrade_resume(
    bt_backup_path: Path,
    write: bool = True,
    create_backup: bool = True,
    skip_bad_files: bool = False,
) -> DowngradeSummary:
    """Convert every version 2 `.fastresume` in `bt_backup_path`.

    With `write` off this is the dry run: the same conversion, nothing
    written, failures reported in the summary instead of raised.

    :raises NotADirectoryError: `bt_backup_path` is not a directory.
    :raises BencodeDecodeError: An unreadable file, unless skipping them.
    :raises FastResumeUpdateError: Writing, and some files failed.
    """
    if not bt_backup_path.is_dir():
        raise NotADirectoryError(bt_backup_path)
    # Everything is read and planned before anything is written, so an
    # unreadable file stops the run with nothing changed.
    summary, converted = plan_all(
        list(iter_resume_data(bt_backup_path, skip_bad_files))
    )
    if not write:
        return summary
    # Only when something will change. The archive name has one-second
    # resolution, so a no-op rerun straight after a conversion would
    # otherwise replace the archive of the originals with converted files.
    if create_backup and converted:
        backup_folder(
            bt_backup_path,
            bt_backup_path / f"fastresume_backup"
            f"{datetime.now().strftime('%Y%m%d%H%M%S')}.zip",
        )
    failures = write_all(converted)
    failures.update(
        (plan.file_path, ValueError(plan.error)) for plan in summary.failing
    )
    if failures:
        raise FastResumeUpdateError(failures)
    return summary
