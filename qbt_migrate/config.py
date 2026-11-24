"""Paths in qBittorrent's own settings, next to the per-torrent ones.

Torrents using Automatic Torrent Management take their location from their
category, and new torrents from the default save path, so migrating only the
`.fastresume` files leaves qBittorrent pointing at the old root for both.

Formats, from qBittorrent's source (src/base/bittorrent/sessionimpl.cpp,
categoryoptions.cpp, src/app/upgrade.cpp):

* `categories.json` in the config directory, written by `QJsonDocument`: an
  object of category name to options, where `save_path` is a string and
  `download_path` is a string (enabled, with a path), `false` (disabled) or
  `null` (follow the global setting).
* `qBittorrent.conf` (`qBittorrent.ini` on Windows and macOS), written by
  `QSettings` in INI format: `BitTorrent/Session/DefaultSavePath` and
  `BitTorrent/Session/TempPath`, stored as `Session\\DefaultSavePath=...`
  under `[BitTorrent]`. Older versions kept the same settings under
  `[Preferences]` as `Downloads\\SavePath` and `Downloads\\TempPath`.

The INI escaping follows qtbase's src/corelib/io/qsettings.cpp, in both the
Qt 5.15 and the Qt 6 version, since qBittorrent 4.x builds use either.
"""

import errno
import json
import logging
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from qbt_migrate.enums import TargetOS
from qbt_migrate.exceptions import ConfigError
from qbt_migrate.methods import convert_slashes, matches_path, replace_path


logger = logging.getLogger(__name__)

CATEGORIES_FILE = "categories.json"
# qBittorrent.conf on Linux, qBittorrent.ini on Windows and macOS.
CONF_FILES = ("qBittorrent.conf", "qBittorrent.ini")
# Left behind by an unclean exit. qBittorrent restores its settings from it on
# the next start, which would silently discard an edit to the real file.
UNCLEAN_CONF_FILES = ("qBittorrent_new.conf", "qBittorrent_new.ini")

CATEGORY_PATH_KEYS = ("save_path", "download_path")
# Full QSettings keys, the way qBittorrent names them in code. In the file the
# first part is the [section] and the rest the key, with "\" for "/".
CONF_PATH_KEYS = (
    "BitTorrent/Session/DefaultSavePath",
    "BitTorrent/Session/TempPath",
    "Preferences/Downloads/SavePath",
    "Preferences/Downloads/TempPath",
)

# The fixed escapes QSettings reads (escapeCodes in iniUnescapedStringList).
_INI_READ_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    '"': '"',
    "?": "?",
    "'": "'",
    "\\": "\\",
}
# The fixed escapes QSettings writes (the switch in iniEscapedString).
_INI_WRITE_ESCAPES = {
    "\0": "\\0",
    "\a": "\\a",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\v": "\\v",
    '"': '\\"',
    "\\": "\\\\",
}
_HEX_DIGITS = "0123456789abcdefABCDEF"
_OCT_DIGITS = "01234567"
# QSettings quotes a value containing any of these, or with outer spaces.
_INI_QUOTE_TRIGGERS = (";", ",", "=")
_UTF8_BOM = "﻿"


@dataclass(frozen=True)
class ConfigChange:
    """One setting's value before and after a migration."""

    key: str
    old: str
    new: str


@dataclass(frozen=True)
class ConfigEdit:
    """A config file, what would change in it, and its new contents."""

    file_path: Path
    changes: tuple[ConfigChange, ...] = ()
    content: bytes = b""


def rewrite_path(
    value: str,
    existing_path: str,
    new_path: str,
    regex_path: bool = False,
    target_os: TargetOS | None = None,
) -> str:
    """`value` migrated the way a `.fastresume` save path would be.

    Values that do not contain the existing path are returned unchanged, so
    unrelated settings are never touched, not even to convert separators.
    """
    # Mirrors FastResume.replace_paths, so a category and the torrents in it
    # end up with the same new path from the same -e/-n/-r/-t arguments.
    if regex_path:
        if not re.search(existing_path, value):
            return value
        value = re.sub(existing_path, new_path, value)
    else:
        if not matches_path(value, existing_path):
            return value
        value = replace_path(value, existing_path, new_path)
    # Only matched values get here, so -t never rewrites a setting that has
    # nothing to do with the paths being migrated.
    if target_os is not None:
        value = convert_slashes(value, target_os)
    return value


def _utf16_units(value: str) -> list[str]:
    """`value` as UTF-16 code units, the unit QSettings escapes in.

    Qt iterates a QString, so a character outside the BMP is two surrogates,
    each written as its own `\\x` escape.
    """
    data = value.encode("utf-16-le", "surrogatepass")
    return [
        chr(int.from_bytes(data[i : i + 2], "little"))
        for i in range(0, len(data), 2)
    ]


def _unescape_one(raw: str, index: int) -> tuple[str | None, int]:
    """Decode the escape after the backslash at `raw[index - 1]`.

    Returns the decoded UTF-16 unit and the index after the escape, or `None`
    for anything QSettings would not read back as part of a plain value.
    """
    code = raw[index : index + 1]
    if code in _INI_READ_ESCAPES:
        return _INI_READ_ESCAPES[code], index + 1
    # "\x" takes every hex digit that follows, "\1" every octal digit
    # (StHexEscape and StOctEscape). `code` may be "" at the end of the value,
    # which a plain `in` would find in any string.
    if code == "x":
        digits, base, start = _HEX_DIGITS, 16, index + 1
    elif code and code in _OCT_DIGITS:
        digits, base, start = _OCT_DIGITS, 8, index
    else:
        # A dangling backslash, or one Qt silently drops: not ours to guess.
        return None, index
    end = start
    while end < len(raw) and raw[end] in digits:
        end += 1
    # "\x" with no digit decodes to nothing in Qt; leave such a value alone.
    if end == start:
        return None, index
    # Qt accumulates into a char16_t, which wraps at 16 bits.
    return chr(int(raw[start:end], base) & 0xFFFF), end


def ini_unescape(raw: str) -> str | None:
    """Decode a QSettings INI value, or `None` if it is not a plain string.

    Lists (an unquoted comma), comments (an unquoted semicolon), `@`-prefixed
    variants and escapes Qt would drop are reported as `None`, so the caller
    leaves the line be.
    """
    # QSettings marks serialised types as @Variant(...)/@ByteArray(...) and
    # writes a string that really starts with "@" as "@@..." (stringToVariant
    # in qtbase's qsettings.cpp). Neither is a path qBittorrent wrote.
    if raw.startswith("@"):
        return None
    units = []
    quoted = False
    index = 0
    while index < len(raw):
        char = raw[index]
        index += 1
        if char == "\\":
            unit, index = _unescape_one(raw, index)
            if unit is None:
                return None
            units.append(unit)
        elif char == '"':
            # Quotes only group; QSettings drops them when reading.
            quoted = not quoted
        elif char in ",;" and not quoted:
            # An unquoted comma makes the value a QStringList, an unquoted
            # semicolon starts a comment (readIniLine).
            return None
        else:
            units.append(char)
    # \x escapes are UTF-16 units: pair up surrogates, and refuse a lone one.
    try:
        return (
            "".join(units)
            .encode("utf-16-le", "surrogatepass")
            .decode("utf-16-le")
        )
    except UnicodeDecodeError:
        return None


def ini_escape(value: str) -> str:
    """Encode a string the way QSettings writes it without a text codec.

    Follows `QSettingsPrivate::iniEscapedString`. Everything outside printable
    ASCII becomes a `\\x` escape, which is how Qt 5 writes it when no codec is
    set (qBittorrent 4.x sets none) and which Qt 6, though it writes raw UTF-8
    itself, still reads back. Raw UTF-8 would be read as Latin-1 by Qt 5.
    """
    out = []
    escape_next_hex = False
    for unit in _utf16_units(value):
        # "\xf6" followed by "a" would read back as the single escape "\xf6a",
        # so Qt escapes a hex digit right after an escape too.
        if escape_next_hex and unit in _HEX_DIGITS:
            out.append(f"\\x{ord(unit):x}")
            continue
        escape_next_hex = False
        if unit in _INI_WRITE_ESCAPES:
            out.append(_INI_WRITE_ESCAPES[unit])
            # "\0" is an octal escape, so the same rule applies after it.
            escape_next_hex = unit == "\0"
        elif ord(unit) <= 0x1F or ord(unit) >= 0x7F:
            out.append(f"\\x{ord(unit):x}")
            escape_next_hex = True
        else:
            out.append(unit)
    escaped = "".join(out)
    # Unquoted, these would split the value or be trimmed when read back.
    if (
        any(char in value for char in _INI_QUOTE_TRIGGERS)
        or escaped.startswith(" ")
        or escaped.endswith(" ")
    ):
        return f'"{escaped}"'
    return escaped


def _read(file_path: Path) -> str:
    """The file as text, with every failure turned into a `ConfigError`."""
    # categories.json comes from QJsonDocument::toJson, which is UTF-8. Qt 6
    # writes INI files as UTF-8, and Qt 5 without a codec writes pure ASCII,
    # which is valid UTF-8 too. Anything else is not a file this code should
    # guess the encoding of.
    try:
        return file_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Could not read {file_path}: {e}") from e


def plan_categories(
    file_path: Path,
    existing_path: str,
    new_path: str,
    regex_path: bool = False,
    target_os: TargetOS | None = None,
) -> ConfigEdit:
    """Category save and download paths that would change.

    :raises ConfigError: If the file cannot be read or is not a JSON object.
    """
    try:
        data = json.loads(_read(file_path))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{file_path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{file_path} does not hold a JSON object")

    changes = []
    for name, options in data.items():
        # Since 4.4.0 every value is an object (CategoryOptions::toJSON in
        # src/base/bittorrent/categoryoptions.cpp); anything else is not ours.
        if not isinstance(options, dict):
            continue
        for key in CATEGORY_PATH_KEYS:
            old = options.get(key)
            # download_path may also be false or null, which hold no path.
            if not isinstance(old, str):
                continue
            new = rewrite_path(
                old, existing_path, new_path, regex_path, target_os
            )
            if new != old:
                # Mutated in place, so key order and every other option are
                # carried over as loaded.
                options[key] = new
                changes.append(ConfigChange(f"{name}: {key}", old, new))
    # Nothing to change means nothing to write, not even a reformat.
    if not changes:
        return ConfigEdit(file_path)
    # Same layout as QJsonDocument::toJson(): four-space indent, UTF-8.
    content = json.dumps(data, indent=4, ensure_ascii=False) + "\n"
    return ConfigEdit(file_path, tuple(changes), content.encode("utf-8"))


def _ini_section(header: str) -> str:
    """The QSettings group a `[header]` line opens, "" for the top level."""
    # Qt trims the name and treats [General] as the top level (readIniFile).
    name = header[1:].partition("]")[0].strip()
    if name.lower() == "general":
        return ""
    return name.replace("\\", "/")


def _ini_full_key(section: str, key: str) -> str:
    """The full QSettings key, with "/" as Qt reads both "\\" and "/"."""
    # Percent-encoded keys (iniEscapedKey) are not decoded: qBittorrent's
    # path keys never need one, so such a line is a different setting.
    key = key.strip().replace("\\", "/")
    return f"{section}/{key}" if section else key


def _display_key(full_key: str) -> str:
    """`BitTorrent/Session/TempPath` as `[BitTorrent] Session\\TempPath`."""
    section, _, key = full_key.partition("/")
    backslash = "\\"
    return f"[{section}] {key.replace('/', backslash)}"


def plan_conf(
    file_path: Path,
    existing_path: str,
    new_path: str,
    regex_path: bool = False,
    target_os: TargetOS | None = None,
) -> ConfigEdit:
    """Default save and incomplete paths that would change.

    Edits only the matching lines and keeps every other byte, including line
    endings, a byte order mark and key order. Parsing and rewriting the whole
    file would reorder and re-escape settings this tool has no business
    touching.

    :raises ConfigError: If the file cannot be read as UTF-8.
    """
    text = _read(file_path)
    # Qt skips a UTF-8 BOM (readIniFile), which an editor may have added. Left
    # in, it would hide the first [section] header from the parser below.
    bom = _UTF8_BOM if text.startswith(_UTF8_BOM) else ""
    # keepends, so CRLF files written on Windows come back out as CRLF.
    lines = text[len(bom) :].splitlines(keepends=True)
    # Keys before the first header belong to QSettings' top level.
    section = ""
    changes = []
    for index, line in enumerate(lines):
        if line.strip().startswith("["):
            section = _ini_section(line.strip())
            continue
        # Split on the first "=" only: QSettings percent-encodes "=" in keys
        # (iniEscapedKey), but a value may contain one. Everything before it
        # is kept verbatim, whichever of the forms Qt accepts it uses.
        key, separator, raw = line.partition("=")
        full_key = _ini_full_key(section, key)
        if not separator or full_key not in CONF_PATH_KEYS:
            continue
        old = ini_unescape(raw.strip())
        if old is None:
            logger.warning(
                f"⚠️ Leaving {_display_key(full_key)} in {file_path} alone, "
                f"its value is not a plain path: {raw.strip()}"
            )
            continue
        new = rewrite_path(old, existing_path, new_path, regex_path, target_os)
        if new == old:
            continue
        line_ending = line[len(line.rstrip("\r\n")) :]
        lines[index] = f"{key}={ini_escape(new)}{line_ending}"
        changes.append(ConfigChange(_display_key(full_key), old, new))
    if not changes:
        return ConfigEdit(file_path)
    return ConfigEdit(
        file_path, tuple(changes), (bom + "".join(lines)).encode("utf-8")
    )


def _check_writable(file_path: Path) -> None:
    """Fail now, while nothing is written, if `file_path` cannot be replaced.

    The settings are written after the `.fastresume` files, so a permission
    problem found only then would leave the two disagreeing.
    """
    target = Path(os.path.realpath(file_path))
    # The directory too: the replacement is created next to the file.
    for path in (target, target.parent):
        if not os.access(path, os.W_OK):
            raise ConfigError(
                f"{path} is not writable by this user, so {file_path.name} "
                f"cannot be updated. Run as the user that owns qBittorrent's "
                f"settings, or fix the permissions."
            )


def plan_config(
    config_dir: Path,
    existing_path: str,
    new_path: str,
    regex_path: bool = False,
    target_os: TargetOS | None = None,
) -> list[ConfigEdit]:
    """Plan every config file found in qBittorrent's config directory.

    Reads, validates and checks write access before anything is written, so a
    bad or read-only file stops the run while it is still a no-op.

    :raises ConfigError: If the directory holds no config file, holds a
    leftover from an unclean exit, or a file cannot be parsed or written.
    """
    if not config_dir.is_dir():
        raise ConfigError(f"Config directory not found: {config_dir}")
    # SettingsStorage::readNativeSettings (src/base/settingsstorage.cpp)
    # prefers a *_new file holding any keys over the real one and renames it
    # over it, so an edit to qBittorrent.conf would vanish on the next start.
    # An empty one is ignored there, so it is ignored here too.
    for name in UNCLEAN_CONF_FILES:
        leftover = config_dir / name
        if leftover.is_file() and leftover.stat().st_size > 0:
            raise ConfigError(
                f"{leftover} exists, left by an unclean exit. "
                f"qBittorrent restores its settings from it on the next "
                f"start, which would undo this change. Start and quit "
                f"qBittorrent once to settle it, then run again."
            )
    # Either file alone is fine: a setup without categories has no
    # categories.json, and Linux and Windows each have only one conf name.
    edits = []
    categories = config_dir / CATEGORIES_FILE
    if categories.is_file():
        edits.append(
            plan_categories(
                categories, existing_path, new_path, regex_path, target_os
            )
        )
    for name in CONF_FILES:
        conf = config_dir / name
        if conf.is_file():
            edits.append(
                plan_conf(conf, existing_path, new_path, regex_path, target_os)
            )
    if not edits:
        raise ConfigError(
            f"No {CATEGORIES_FILE} or {' / '.join(CONF_FILES)} in "
            f"{config_dir}. Point --config-dir at the directory holding "
            f"qBittorrent's settings."
        )
    # Only files that will change need to be writable; the rest are read.
    for edit in edits:
        if edit.changes:
            _check_writable(edit.file_path)
    return edits


def _write_in_place(file_path: Path, content: bytes) -> None:
    """Overwrite `file_path` through its existing inode.

    Not atomic, but the content is fully encoded already, and writing before
    truncating never leaves the file empty.
    """
    with open(file_path, "r+b") as handle:
        handle.write(content)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())


def write_atomic(file_path: Path, content: bytes) -> None:
    """Replace `file_path` with `content`, never leaving it half written.

    Written to a temporary file in the same directory, then renamed over the
    original, which keeps its mode and, where permitted, its owner. A
    container running as root against files owned by the qBittorrent user
    would otherwise leave settings the client cannot rewrite.

    Two cases cannot be renamed over and are written in place instead: a file
    with several hard links, which a rename would split, and a file that is a
    mount point of its own (a single-file Docker bind mount), which fails
    with EBUSY.
    """
    # Write through a symlink to its target, as open() would, instead of
    # replacing the link with a regular file and leaving the target stale.
    target = Path(os.path.realpath(file_path))
    # Read before writing anything, so the original's metadata is what the
    # replacement gets even if something else touches the file meanwhile.
    original = target.stat()
    if original.st_nlink > 1:
        logger.warning(
            f"⚠️ {file_path} has {original.st_nlink} hard links. Writing it "
            f"in place so they keep pointing at the same file."
        )
        _write_in_place(target, content)
        return
    # Same directory, so os.replace is a rename on one filesystem and
    # therefore atomic; a dot prefix keeps it out of casual listings.
    descriptor, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            # On disk before the rename, or a crash could leave the renamed
            # file empty on filesystems that reorder metadata and data.
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IMODE(original.st_mode))
        # Windows has no os.chown; ownership is not carried over there.
        if hasattr(os, "chown"):
            try:
                os.chown(temp_path, original.st_uid, original.st_gid)
            except OSError as e:
                # Non-root cannot give a file away. The file is still
                # written, just owned by whoever ran the tool.
                logger.warning(
                    f"⚠️ Could not keep the owner of {file_path}: {e}"
                )
        try:
            os.replace(temp_path, target)
        except OSError as e:
            if e.errno != errno.EBUSY:
                raise
            logger.warning(
                f"⚠️ {file_path} is a mount point of its own (a single-file "
                f"bind mount?) and cannot be replaced. Writing it in place."
            )
            temp_path.unlink()
            _write_in_place(target, content)
    # BaseException too, so Ctrl-C does not leave the temporary file behind.
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def apply_config(edits: list[ConfigEdit]) -> int:
    """Write every edit that changes something. Returns the count written.

    :raises ConfigError: If a file cannot be written. Files written before it
    stay written; the one that failed is left as it was.
    """
    written = 0
    for edit in edits:
        # Planned files with no change were only read for the backup.
        if not edit.changes:
            continue
        try:
            write_atomic(edit.file_path, edit.content)
        except OSError as e:
            raise ConfigError(f"Could not write {edit.file_path}: {e}") from e
        # Logged after the write, so the log never claims a change that a
        # failed write did not make.
        for change in edit.changes:
            logger.info(
                f"⚙️ {edit.file_path.name} {change.key}: "
                f"'{change.old}' -> '{change.new}'"
            )
        written += 1
    return written
