"""`--config-dir`: category, default and incomplete paths in the settings.

Torrents under Automatic Torrent Management take their location from their
category, so migrating only the `.fastresume` files leaves qBittorrent
pointing new and category-managed torrents at the old root.
"""

import errno
import json
import os
import zipfile

import pytest

from qbt_migrate.classes import FastResume
from qbt_migrate.cli import main
from qbt_migrate.config import (
    ConfigChange,
    ConfigEdit,
    apply_config,
    ini_escape,
    ini_unescape,
    plan_categories,
    plan_conf,
    plan_config,
    rewrite_path,
    write_atomic,
)
from qbt_migrate.enums import TargetOS
from qbt_migrate.exceptions import ConfigError, QBTMigrateError


# As qBittorrent 4.4+ writes it: QJsonDocument::toJson(), indented.
CATEGORIES = {
    "movies": {
        "download_path": "/data/incomplete/movies",
        "save_path": "/data/movies",
    },
    "tv": {"download_path": False, "save_path": "/data/tv"},
    "music": {"download_path": None, "save_path": "/elsewhere/music"},
    "uncategorised": {"save_path": ""},
}

# As QSettings writes it on Linux, with keys qbt_migrate must not touch.
CONF = (
    "[Application]\n"
    "FileLogger\\Path=/data/logs\n"
    "\n"
    "[BitTorrent]\n"
    "Session\\DefaultSavePath=/data/\n"
    "Session\\Port=6881\n"
    "Session\\TempPath=/data/incomplete/\n"
    "Session\\TempPathEnabled=true\n"
    "\n"
    "[Preferences]\n"
    "Downloads\\SavePath=/data/\n"
    "Downloads\\TempPath=/data/incomplete/\n"
    "WebUI\\Port=8080\n"
)

RELEVANT = {"save_path": "/data/movies/x", "qBt-savePath": "/data/movies/x"}


@pytest.fixture
def config_dir(temp_dir):
    """An empty qBittorrent config directory beside the BT_backup one."""
    path = temp_dir / "config"
    path.mkdir()
    return path


@pytest.fixture
def write_categories(config_dir):
    def _write(data: object = CATEGORIES):
        path = config_dir / "categories.json"
        path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        return path

    return _write


@pytest.fixture
def write_conf(config_dir):
    def _write(text: str = CONF, name: str = "qBittorrent.conf"):
        path = config_dir / name
        path.write_bytes(text.encode("utf-8"))
        return path

    return _write


# rewrite_path


def test_rewrite_matches_the_fastresume_rules():
    """A category path moves the same way a torrent's save path does."""

    assert rewrite_path("/data/movies", "/data", "/mnt/data") == (
        "/mnt/data/movies"
    )


def test_rewrite_leaves_unrelated_values_alone():
    """Settings outside the migrated root are not touched at all."""

    # Not even a separator conversion: it is not ours to touch.
    assert (
        rewrite_path("D:\\other", "/data", "/mnt", target_os=TargetOS.POSIX)
        == "D:\\other"
    )


def test_rewrite_converts_separators_of_matched_values():
    """-t converts the separators of values that matched."""

    assert (
        rewrite_path(
            "D:/Torrents/movies", "D:/", "/mnt/d/", target_os=TargetOS.POSIX
        )
        == "/mnt/d/Torrents/movies"
    )


def test_rewrite_regex():
    """-r uses the regex for both matching and replacing."""

    assert (
        rewrite_path("/data/movies", r"^/data/(\w+)$", r"/mnt/\1", True)
        == "/mnt/movies"
    )
    assert rewrite_path("/other", r"^/data/(\w+)$", r"/mnt/\1", True) == (
        "/other"
    )


# INI value encoding, as Qt's QSettingsPrivate::iniEscapedString does it


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("/data/", "/data/"),
        ("D:\\\\Downloads\\\\", "D:\\Downloads\\"),
        ('"/data/a;b"', "/data/a;b"),
        ('"/data/a,b"', "/data/a,b"),
        ('/data/\\"q\\"', '/data/"q"'),
        ("", ""),
        # Qt 5 without a codec writes non-ASCII as UTF-16 \x escapes.
        ("/data/Gr\\xf6\\xdf\\x65", "/data/Größe"),
        ("/data/\\xd83d\\xde00", "/data/\U0001f600"),
        ("/data/\\101\\t", "/data/A\t"),
    ],
)
def test_ini_unescape(raw, value):
    """QSettings' backslash escapes and quoting decode to the stored path."""

    assert ini_unescape(raw) == value


@pytest.mark.parametrize(
    "raw",
    [
        "/a, /b",  # a string list
        "@Variant(\\0\\0)",  # a serialised QVariant
        "/data/\\q",  # an escape Qt silently drops
        "/data/\\x",  # \x without a digit, which Qt reads as nothing
        "/data/\\",  # a dangling backslash
        "/data/a;b",  # Qt reads an unquoted ; as the start of a comment
        "/data/\\xd83d",  # half a surrogate pair
    ],
)
def test_ini_unescape_refuses_what_is_not_a_plain_path(raw):
    """Lists, variants and unknown escapes are reported, not guessed at."""

    assert ini_unescape(raw) is None


@pytest.mark.parametrize(
    ("value", "raw"),
    [
        ("/mnt/data/", "/mnt/data/"),
        ("D:\\Downloads\\", "D:\\\\Downloads\\\\"),
        ("/mnt/a;b", '"/mnt/a;b"'),
        ("/mnt/a=b", '"/mnt/a=b"'),
        (" /mnt", '" /mnt"'),
        ("/mnt ", '"/mnt "'),
        ('/mnt/"q"', '/mnt/\\"q\\"'),
        # Hex digits right after an escape are escaped too, or Qt would
        # read them as part of it.
        ("/mnt/Größe", "/mnt/Gr\\xf6\\xdf\\x65"),
        ("/mnt/\U0001f600", "/mnt/\\xd83d\\xde00"),
        # \t has no such rule, only \0 and \x do.
        ("/mnt/\tdata", "/mnt/\\tdata"),
        ("/mnt/\x00" + "1", "/mnt/\\0\\x31"),
        ("/mnt/\x7f", "/mnt/\\x7f"),
    ],
)
def test_ini_escape(value, raw):
    """Encoding matches QSettings and round-trips through the decoder."""

    assert ini_escape(value) == raw
    assert ini_unescape(raw) == value


def test_ini_escape_output_is_ascii():
    """Qt 5 reads raw bytes as Latin-1, so nothing outside ASCII is written."""

    assert ini_escape("/mnt/Größe/日本").isascii()


# categories.json


def test_categories_object_form(write_categories):
    """save_path and download_path move; false and null stay as they are."""

    path = write_categories()

    edit = plan_categories(path, "/data", "/srv/media")

    assert edit.changes == (
        ConfigChange("movies: save_path", "/data/movies", "/srv/media/movies"),
        ConfigChange(
            "movies: download_path",
            "/data/incomplete/movies",
            "/srv/media/incomplete/movies",
        ),
        ConfigChange("tv: save_path", "/data/tv", "/srv/media/tv"),
    )
    written = json.loads(edit.content.decode("utf-8"))
    # download_path false and null are not paths and must survive as they are.
    assert written["tv"]["download_path"] is False
    assert written["music"] == CATEGORIES["music"]
    assert written["uncategorised"] == {"save_path": ""}
    assert list(written) == list(CATEGORIES)


def test_categories_layout_matches_qbittorrent(write_categories):
    """The rewritten file has QJsonDocument::toJson's layout, raw UTF-8."""

    path = write_categories({"a": {"save_path": "/data/ä"}})

    edit = plan_categories(path, "/data", "/mnt")

    assert edit.content.decode("utf-8") == (
        '{\n    "a": {\n        "save_path": "/mnt/ä"\n    }\n}\n'
    )


def test_categories_from_windows(write_categories):
    """Windows categories with forward slashes still match a backslash -e."""

    # qBittorrent writes Path::data(), which uses forward slashes everywhere.
    path = write_categories({"a": {"save_path": "D:/Torrents/a"}})

    edit = plan_categories(path, "D:\\", "/mnt/d/", target_os=TargetOS.POSIX)

    assert edit.changes[0].new == "/mnt/d/Torrents/a"


def test_categories_skip_non_object_entries(write_categories):
    """A value that is not an object is kept and not rewritten."""

    path = write_categories({"odd": "/data/x", "a": {"save_path": "/data"}})

    edit = plan_categories(path, "/data", "/mnt")

    assert [change.key for change in edit.changes] == ["a: save_path"]
    assert json.loads(edit.content)["odd"] == "/data/x"


def test_categories_without_matches_plan_nothing(write_categories):
    """No match means no content to write."""

    path = write_categories()

    edit = plan_categories(path, "/nowhere", "/mnt")

    assert edit == ConfigEdit(path)


@pytest.mark.parametrize(
    "content",
    [b"{not json", b"", b'["a"]', b"\xff\xfe{}"],
    ids=["malformed", "empty", "not-an-object", "not-utf8"],
)
def test_categories_unparseable(config_dir, content):
    """An unreadable categories.json is a ConfigError naming the file."""

    path = config_dir / "categories.json"
    path.write_bytes(content)

    with pytest.raises(ConfigError) as excinfo:
        plan_categories(path, "/data", "/mnt")

    assert str(path) in str(excinfo.value)
    assert isinstance(excinfo.value, QBTMigrateError)


# qBittorrent.conf


def test_conf_rewrites_only_path_lines(write_conf):
    """Only the four path keys change; every other line stays as it was."""

    path = write_conf()

    edit = plan_conf(path, "/data", "/srv/media")

    assert [change.key for change in edit.changes] == [
        "[BitTorrent] Session\\DefaultSavePath",
        "[BitTorrent] Session\\TempPath",
        "[Preferences] Downloads\\SavePath",
        "[Preferences] Downloads\\TempPath",
    ]
    expected = (
        CONF.replace("SavePath=/data/", "SavePath=/srv/media/")
        .replace("TempPath=/data/", "TempPath=/srv/media/")
        .encode("utf-8")
    )
    # FileLogger\Path matched too, but is not a download location.
    assert b"FileLogger\\Path=/data/logs" in expected
    assert edit.content == expected


def test_conf_keeps_crlf_and_escapes_windows_paths(write_conf):
    """CRLF survives and Windows paths are written with doubled backslashes."""

    path = write_conf(
        "[BitTorrent]\r\n"
        "Session\\DefaultSavePath=X:\\\\Torrents\\\\\r\n"
        "Session\\Port=6881\r\n",
        name="qBittorrent.ini",
    )

    edit = plan_conf(path, "X:\\Torrents", "Z:\\New")

    assert edit.changes == (
        ConfigChange(
            "[BitTorrent] Session\\DefaultSavePath",
            "X:\\Torrents\\",
            "Z:\\New\\",
        ),
    )
    assert edit.content == (
        b"[BitTorrent]\r\n"
        b"Session\\DefaultSavePath=Z:\\\\New\\\\\r\n"
        b"Session\\Port=6881\r\n"
    )


def test_conf_same_key_in_another_section_is_ignored(write_conf):
    """A path key name under the wrong section is not ours."""

    path = write_conf("[Other]\nSession\\DefaultSavePath=/data/\n")

    assert plan_conf(path, "/data", "/mnt") == ConfigEdit(path)


def test_conf_last_line_without_newline(write_conf):
    """A file without a final newline does not gain one."""

    path = write_conf("[BitTorrent]\nSession\\TempPath=/data/t")

    edit = plan_conf(path, "/data", "/mnt")

    assert edit.content == b"[BitTorrent]\nSession\\TempPath=/mnt/t"


def test_conf_leaves_values_it_cannot_decode(write_conf, caplog):
    """A value it cannot decode is left alone with a warning."""

    path = write_conf("[BitTorrent]\nSession\\TempPath=/data/a, /data/b\n")

    with caplog.at_level("WARNING", logger="qbt_migrate.config"):
        edit = plan_conf(path, "/data", "/mnt")

    assert edit.changes == ()
    assert "Leaving [BitTorrent] Session\\TempPath" in caplog.text


def test_conf_not_utf8(write_conf, config_dir):
    """A conf that is not UTF-8 is a ConfigError, not a guess."""

    path = config_dir / "qBittorrent.conf"
    path.write_bytes(b"[BitTorrent]\nSession\\TempPath=/data/\xff\n")

    with pytest.raises(ConfigError):
        plan_conf(path, "/data", "/mnt")


def test_conf_non_ascii_for_qt5(write_conf):
    """A non-ASCII new path is written as escapes Qt 5 and Qt 6 both read."""

    path = write_conf("[BitTorrent]\nSession\\DefaultSavePath=/data/Filme\n")

    edit = plan_conf(path, "/data", "/srv/Größe")

    assert edit.content == (
        b"[BitTorrent]\n"
        b"Session\\DefaultSavePath=/srv/Gr\\xf6\\xdf\\x65/Filme\n"
    )
    # Qt 5 without a codec reads the bytes as Latin-1, which for pure ASCII
    # is the same text, and decodes the escapes from it.
    raw = edit.content.decode("latin-1").split("=", 1)[1].strip()
    assert ini_unescape(raw) == "/srv/Größe/Filme"


def test_conf_migrates_escaped_old_values(write_conf):
    """A value Qt 5 already wrote with escapes is decoded and migrated."""

    path = write_conf(
        "[BitTorrent]\nSession\\TempPath=/data/Gr\\xf6\\xdf\\x65/x\n"
    )

    edit = plan_conf(path, "/data", "/srv")

    assert edit.changes[0].old == "/data/Größe/x"
    assert edit.content.endswith(b"=/srv/Gr\\xf6\\xdf\\x65/x\n")


def test_conf_with_byte_order_mark(write_conf):
    """A BOM, which Qt skips, neither hides the first section nor is lost."""

    path = write_conf("\ufeff[BitTorrent]\nSession\\DefaultSavePath=/data/\n")

    edit = plan_conf(path, "/data", "/srv")

    assert len(edit.changes) == 1
    assert edit.content == (
        b"\xef\xbb\xbf[BitTorrent]\nSession\\DefaultSavePath=/srv/\n"
    )


@pytest.mark.parametrize(
    "text",
    [
        "[ BitTorrent ]\nSession\\TempPath=/data/\n",
        "[BitTorrent]\nSession/TempPath=/data/\n",
        "[General]\nBitTorrent\\Session\\TempPath=/data/\n",
        "BitTorrent/Session/TempPath=/data/\n[Other]\n",
        "[BitTorrent]\n  Session\\TempPath = /data/\n",
    ],
    ids=["spaced-section", "slash", "general", "top-level", "spaced-key"],
)
def test_conf_key_forms_qt_accepts(write_conf, text):
    """Every way Qt spells the same key is found, and its spelling kept."""

    path = write_conf(text)

    edit = plan_conf(path, "/data", "/srv")

    assert [change.key for change in edit.changes] == [
        "[BitTorrent] Session\\TempPath"
    ]
    # Only the value changes; the key keeps its spelling and spacing.
    expected = text.replace("= /data/", "=/srv/").replace("=/data/", "=/srv/")
    assert edit.content.decode("utf-8") == expected


# plan_config


def test_plan_config_reads_every_file(write_categories, write_conf):
    """categories.json and both conf names are all planned."""

    write_categories()
    write_conf()
    write_conf(name="qBittorrent.ini")

    edits = plan_config(write_conf().parent, "/data", "/mnt")

    assert [edit.file_path.name for edit in edits] == [
        "categories.json",
        "qBittorrent.conf",
        "qBittorrent.ini",
    ]


def test_plan_config_one_file_is_enough(write_conf):
    """A directory with only a conf is valid."""

    path = write_conf()

    edits = plan_config(path.parent, "/data", "/mnt")

    assert [edit.file_path for edit in edits] == [path]


def test_plan_config_missing_directory(temp_dir):
    """A --config-dir that does not exist is an error."""

    with pytest.raises(ConfigError, match="not found"):
        plan_config(temp_dir / "nope", "/data", "/mnt")


def test_plan_config_empty_directory(config_dir):
    """A directory with none of the files is an error, not a silent no-op."""

    with pytest.raises(ConfigError, match="No categories.json"):
        plan_config(config_dir, "/data", "/mnt")


def test_plan_config_ignores_an_empty_unclean_exit_file(write_conf):
    """qBittorrent ignores an empty *_new file, so it does not block."""

    path = write_conf()
    (path.parent / "qBittorrent_new.conf").write_bytes(b"")

    assert len(plan_config(path.parent, "/data", "/srv")) == 1


def test_plan_config_refuses_unwritable_files(write_conf, monkeypatch):
    """A file that would change but cannot be written stops the plan."""

    path = write_conf()
    real_access = os.access

    def access(target, mode):
        return target != path and real_access(target, mode)

    monkeypatch.setattr(os, "access", access)

    with pytest.raises(ConfigError, match="is not writable"):
        plan_config(path.parent, "/data", "/srv")
    # Nothing to change, nothing to write, nothing to check.
    assert plan_config(path.parent, "/nowhere", "/srv")


@pytest.mark.parametrize(
    "name", ["qBittorrent_new.conf", "qBittorrent_new.ini"]
)
def test_plan_config_refuses_after_unclean_exit(write_conf, name):
    """A leftover *_new file stops the run, since it would undo the edit."""

    path = write_conf()
    (path.parent / name).write_text("[BitTorrent]\n")

    with pytest.raises(ConfigError, match="unclean exit"):
        plan_config(path.parent, "/data", "/mnt")


# Writing


def test_write_atomic_keeps_mode(write_conf):
    """The replacement keeps the mode and leaves no temporary file."""

    path = write_conf()
    path.chmod(0o640)

    write_atomic(path, b"new")

    assert path.read_bytes() == b"new"
    assert path.stat().st_mode & 0o777 == 0o640
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_write_atomic_warns_when_owner_cannot_be_kept(
    write_conf, monkeypatch, caplog
):
    """A failed chown warns but still writes."""

    path = write_conf()

    def chown(*args):
        raise PermissionError("not permitted")

    monkeypatch.setattr(os, "chown", chown)
    with caplog.at_level("WARNING", logger="qbt_migrate.config"):
        write_atomic(path, b"new")

    assert path.read_bytes() == b"new"
    assert "Could not keep the owner" in caplog.text


def test_write_atomic_without_chown(write_conf, monkeypatch):
    """Platforms without os.chown still write."""

    path = write_conf()
    monkeypatch.delattr(os, "chown")

    write_atomic(path, b"new")

    assert path.read_bytes() == b"new"


def test_write_atomic_failure_leaves_the_original(write_conf, monkeypatch):
    """A failed rename leaves the original intact and no temporary file."""

    path = write_conf()

    def replace(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(OSError, match="disk full"):
        write_atomic(path, b"new")

    assert path.read_bytes() == CONF.encode("utf-8")
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_write_atomic_through_a_symlink(write_conf, temp_dir):
    """A symlinked file is updated at its target, and stays a symlink."""

    target = write_conf()
    link = temp_dir / "link.conf"
    link.symlink_to(target)

    write_atomic(link, b"new")

    assert link.is_symlink()
    assert target.read_bytes() == b"new"


def test_write_atomic_keeps_hard_links(write_conf, temp_dir, caplog):
    """A hard-linked file is written in place, so the links stay together."""

    path = write_conf()
    other = temp_dir / "other.conf"
    os.link(path, other)

    with caplog.at_level("WARNING", logger="qbt_migrate.config"):
        write_atomic(path, b"new")

    assert other.read_bytes() == b"new"
    assert "hard links" in caplog.text


def test_write_atomic_on_a_bind_mounted_file(write_conf, monkeypatch, caplog):
    """EBUSY from a single-file mount falls back to writing in place."""

    path = write_conf()

    def replace(*args):
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(os, "replace", replace)
    with caplog.at_level("WARNING", logger="qbt_migrate.config"):
        write_atomic(path, b"new")

    assert path.read_bytes() == b"new"
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    assert "mount point" in caplog.text


def test_apply_config_writes_only_changing_files(write_conf, write_categories):
    """Files without changes are not rewritten."""

    conf = write_conf()
    categories = write_categories()
    before = categories.read_bytes()
    edits = plan_config(conf.parent, "/data/incomplete", "/mnt/incomplete")
    unchanged = ConfigEdit(categories)

    assert apply_config([edits[1], unchanged]) == 1

    assert b"TempPath=/mnt/incomplete/" in conf.read_bytes()
    assert categories.read_bytes() == before


def test_apply_config_write_failure(write_conf, monkeypatch):
    """A write failure is reported as a ConfigError."""

    path = write_conf()
    edits = plan_config(path.parent, "/data", "/mnt")

    def replace(*args):
        raise PermissionError("read-only")

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(ConfigError, match="Could not write"):
        apply_config(edits)


# CLI


def test_cli_empty_config_dir(write_fastresume, temp_dir, cli_args, caplog):
    """--config-dir "" is a bad argument, not the current directory."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args(
        "-b", str(temp_dir), "-e", "/data", "-n", "/mnt", "--config-dir", " "
    )

    assert main() == 2
    assert "--config-dir is empty" in caplog.text


def test_cli_dry_run_lists_settings_and_writes_nothing(
    write_fastresume, write_categories, write_conf, temp_dir, cli_args, caplog
):
    """--dry-run lists every setting per key and writes nothing."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    categories = write_categories()
    conf = write_conf()
    before = (categories.read_bytes(), conf.read_bytes())
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/srv/media",
        "-d",
        "--config-dir",
        str(conf.parent),
    )

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        assert main() is None

    assert (categories.read_bytes(), conf.read_bytes()) == before
    assert (
        "categories.json  movies: save_path  '/data/movies' -> "
        "'/srv/media/movies'" in caplog.text
    )
    assert (
        "qBittorrent.conf  [BitTorrent] Session\\DefaultSavePath  "
        "'/data/' -> '/srv/media/'" in caplog.text
    )
    assert "7 qBittorrent settings would be updated" in caplog.text


def test_cli_dry_run_with_nothing_to_change(
    write_fastresume, write_conf, temp_dir, cli_args, caplog
):
    """A dry run with no matching settings says so."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    conf = write_conf("[BitTorrent]\nSession\\TempPath=/other/\n")
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/mnt",
        "-d",
        "--config-dir",
        str(conf.parent),
    )

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        assert main() is None

    assert "0 qBittorrent settings would be updated" in caplog.text


def test_cli_dry_run_without_config_dir_says_nothing_about_it(
    write_fastresume, temp_dir, cli_args, caplog
):
    """Without --config-dir the output is unchanged."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/data", "-n", "/mnt", "-d")

    with caplog.at_level("INFO", logger="qbt_migrate.cli"):
        assert main() is None

    assert "qBittorrent setting" not in caplog.text


def test_cli_dry_run_on_malformed_config(
    write_fastresume, config_dir, temp_dir, cli_args, caplog
):
    """A malformed config file fails a dry run with exit 1."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    (config_dir / "categories.json").write_text("{")
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/mnt",
        "-d",
        "--config-dir",
        str(config_dir),
    )

    assert main() == 1
    assert "is not valid JSON" in caplog.text


def test_cli_migrates_settings_and_backs_them_up(
    write_fastresume, write_categories, write_conf, temp_dir, cli_args, caplog
):
    """Settings are migrated and the originals land in the backup zip."""

    resume = write_fastresume("a.fastresume", dict(RELEVANT))
    categories = write_categories()
    conf = write_conf()
    original = (categories.read_bytes(), conf.read_bytes())
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/srv/media",
        "--config-dir",
        str(conf.parent),
    )

    with caplog.at_level("INFO"):
        assert main() is None

    assert FastResume(resume).save_path == "/srv/media/movies/x"
    assert json.loads(categories.read_bytes())["movies"]["save_path"] == (
        "/srv/media/movies"
    )
    assert b"Session\\DefaultSavePath=/srv/media/\n" in conf.read_bytes()
    assert "Updated 2 qBittorrent settings files" in caplog.text
    (archive,) = temp_dir.glob("fastresume_backup*.zip")
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.read("config/categories.json") == original[0]
        assert zipped.read("config/qBittorrent.conf") == original[1]
        assert "a.fastresume" in zipped.namelist()


def test_cli_without_config_dir_backs_up_only_bt_backup(
    write_fastresume, temp_dir, cli_args
):
    """Without --config-dir the backup zip is as before."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    cli_args("-b", str(temp_dir), "-e", "/data", "-n", "/mnt")

    assert main() is None

    (archive,) = temp_dir.glob("fastresume_backup*.zip")
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.namelist() == ["a.fastresume"]


def test_cli_single_settings_file(
    write_fastresume, write_conf, temp_dir, cli_args, caplog
):
    """One changed file is reported in the singular."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    conf = write_conf()
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/mnt",
        "-z",
        "--config-dir",
        str(conf.parent),
    )

    with caplog.at_level("INFO"):
        assert main() is None

    assert "Updated 1 qBittorrent settings file." in caplog.text


def test_cli_settings_without_matches(
    write_fastresume, write_conf, temp_dir, cli_args, caplog
):
    """Settings without matches are left byte for byte."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    conf = write_conf("[BitTorrent]\nSession\\TempPath=/other/\n")
    before = conf.read_bytes()
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/mnt",
        "-z",
        "--config-dir",
        str(conf.parent),
    )

    with caplog.at_level("INFO"):
        assert main() is None

    assert conf.read_bytes() == before
    assert "Updated 0 qBittorrent settings files" in caplog.text


def test_cli_malformed_config_changes_nothing(
    write_fastresume, config_dir, temp_dir, cli_args, caplog
):
    """A malformed config stops the run before any fastresume or backup."""

    resume = write_fastresume("a.fastresume", dict(RELEVANT))
    before = resume.read_bytes()
    (config_dir / "categories.json").write_text('{"a": ')
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/mnt",
        "--config-dir",
        str(config_dir),
    )

    assert main() == 1

    assert resume.read_bytes() == before
    assert list(temp_dir.glob("fastresume_backup*.zip")) == []
    assert "Nothing was changed" in caplog.text


def test_cli_partial_fastresume_failure_keeps_settings(
    write_fastresume, write_conf, temp_dir, cli_args, caplog, monkeypatch
):
    """Settings stay unchanged when any fastresume update failed."""

    write_fastresume("a.fastresume", dict(RELEVANT))
    conf = write_conf()
    before = conf.read_bytes()

    def replace_paths(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(FastResume, "replace_paths", replace_paths)
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/mnt",
        "-z",
        "--config-dir",
        str(conf.parent),
    )

    assert main() == 1

    assert conf.read_bytes() == before
    assert "qBittorrent settings were not changed" in caplog.text


@pytest.mark.parametrize(
    ("flags", "recovery"),
    [
        (["-z"], "No backup archive was made"),
        ([], "Restore the settings from the backup archive"),
    ],
    ids=["skip-backup", "with-backup"],
)
def test_cli_settings_write_failure(
    write_fastresume,
    write_conf,
    temp_dir,
    cli_args,
    caplog,
    monkeypatch,
    flags,
    recovery,
):
    """A late settings write failure exits 1 and names a real recovery."""

    resume = write_fastresume("a.fastresume", dict(RELEVANT))
    conf = write_conf()

    def replace(*args):
        raise PermissionError("read-only")

    monkeypatch.setattr(os, "replace", replace)
    cli_args(
        "-b",
        str(temp_dir),
        "-e",
        "/data",
        "-n",
        "/mnt",
        *flags,
        "--config-dir",
        str(conf.parent),
    )

    assert main() == 1

    assert recovery in caplog.text
    # FastResume.save writes in place, so it is not affected by the patch.
    assert FastResume(resume).save_path == "/mnt/movies/x"
    assert "The .fastresume files were updated" in caplog.text
