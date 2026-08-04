"""Recovering a torrent's display name.

A `.fastresume` is named after the 40 character info hash, which tells a user
nothing about which torrent they are looking at. The name is recoverable, but
not from a single key.

Per qBittorrent's `BencodeResumeDataStorage::Worker::store` and libtorrent's
`write_resume_data`:

* `qBt-name` is always written, but is an empty string unless the user renamed
  the torrent inside qBittorrent
* libtorrent writes `name` only when it is non-empty
* qBittorrent **extracts** the `info` dictionary out of the resume data and
  writes it to a sibling `<hash>.torrent`, so for a normal torrent that file
  holds the only copy of the name

So it is a fallback chain ending at the hash.
"""

import logging
from pathlib import Path
from typing import Any

import bencodepy
from bencodepy.exceptions import BencodeDecodeError


logger = logging.getLogger(__name__)

bencode = bencodepy.Bencode(encoding="utf-8", encoding_fallback="all")

# qBittorrent's own name, always present but often blank.
KEY_QBT_NAME = "qBt-name"
# libtorrent's, present only when non-empty.
KEY_NAME = "name"
# The torrent's info dictionary, normally moved out to the sibling .torrent.
KEY_INFO = "info"

TORRENT_SUFFIX = ".torrent"


def name_from_info(data: dict[str, Any]) -> str:
    """`info.name` from a bencoded dict, or "" when absent."""
    info = data.get(KEY_INFO)
    if not isinstance(info, dict):
        return ""
    name = info.get(KEY_NAME)
    return name.strip() if isinstance(name, str) else ""


def name_from_data(data: dict[str, Any]) -> str:
    """Best name available from resume data alone, or "" if none."""
    for key in (KEY_QBT_NAME, KEY_NAME):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return name_from_info(data)


def name_from_torrent_file(path: Path) -> str:
    """`info.name` from a `.torrent`, or "" if it cannot be read.

    Deliberately quiet: a missing or corrupt metadata file only costs a nicer
    label, and refusing to migrate over that would be absurd.
    """
    try:
        data = bencode.read(path)
    except (OSError, BencodeDecodeError, ValueError) as e:
        logger.debug(f"Could not read {path} for a torrent name: {e}")
        return ""
    return name_from_info(data) if isinstance(data, dict) else ""


def torrent_name(file_path: Path, data: dict[str, Any]) -> str:
    """The display name for a `.fastresume`, falling back to its stem.

    Never raises and never returns empty, so callers can use it directly as
    a label. A magnet link with no metadata yet has no `.torrent` at all, which
    is why the hash remains the last resort.
    """
    return (
        name_from_data(data)
        or name_from_torrent_file(file_path.with_suffix(TORRENT_SUFFIX))
        or file_path.stem
    )
