# Changelog

## Unreleased

Added:

* Torrents are identified by name instead of the 40 character info hash their
  `.fastresume` is named after, in dry run output and in failure messages. The
  name is resolved from `qBt-name`, then libtorrent's `name`, then an embedded
  `info` dictionary, then the sibling `<hash>.torrent` (where qBittorrent
  actually keeps it), falling back to the hash for a magnet with no metadata yet.
* `MigrationPlan.name` and `FastResume.name` for library users

A missing or corrupt `.torrent` only costs the nicer label; it never affects a
migration.

## 3.2.0 (2026-08-04)

Added:

* Refuses to write while qBittorrent is running, since it holds resume data in
  memory and writes `.fastresume` files back out on exit, silently reverting the
  migration. Interactively it offers to stop it; `-k` / `--stop-qbittorrent`
  skips the question. A normal quit is sent, never a force kill, which would
  skip the resume data flush, and the process list is polled until the process
  is actually gone before anything is written.
* `--ignore-running` to override the check
* `--dry-run` is exempt from the check, since it writes nothing

Detection is best effort and finds nothing from inside a container, where
`/proc` only shows the container's own processes.

## 3.1.0 (2026-08-04)

Added:

* `-d` / `--dry-run` shows what every relevant `.fastresume` would become, per
  key, and writes nothing. Values are quoted so leading and trailing separators
  are visible, which is the most common way to get a pattern wrong. Files that
  would fail are reported too, so a dry run surfaces problems rather than only
  successes.
* `QBTBatchMove.plan()` and `FastResume.plan_paths()` return the same
  information as structured `MigrationPlan` objects for library users

## 3.0.0 (2026-08-04)

Breaking:

* Minimum Python is now 3.10. 3.8 went EOL Oct 2024 and 3.9 Oct 2025. `2.3.2`
  stays installable on older interpreters.
* The CLI exits non-zero when work fails: `1` if any `.fastresume` could not be
  read or written, `2` for bad or missing arguments. It previously exited `0`
  regardless. Scripts checking the exit code will start seeing failures they
  were silently ignoring.
* `QBTBatchMove.run()` raises `FastResumeUpdateError` when any file failed,
  after attempting the whole batch.
* BT_backup auto-detection now resolves the way qBittorrent does, so the
  detected path changes on Linux (current XDG layout preferred over the legacy
  `data/` subdirectory) and on macOS (`~/Library/Application Support`, which was
  previously never checked).
* `set_save_paths()` no longer overwrites an existing `qBt-downloadPath` with
  the save path when no replacement download path is given.
* Docker `latest` now tracks releases instead of every push to master. Use the
  `master` tag for the old behavior.

Fixed:

* Paths are matched under both separator conventions, so a Windows-written
  fastresume no longer keeps its drive letter in `qBt-savePath` after a
  migration to POSIX. This is what made runs look non-deterministic and appear
  to need several passes. ([#75](https://github.com/jslay88/qbt_migrate/issues/75))
* Worker failures are reported instead of dying on an unjoined thread while the
  run claimed success
* No prompting when nothing is attached to stdin, so `docker run` without `-it`
  works instead of raising `EOFError`. ([#69](https://github.com/jslay88/qbt_migrate/issues/69))
* An unreadable `.fastresume` without `-s` explains itself and points at
  `--skip-bad-files` instead of printing a traceback. ([#65](https://github.com/jslay88/qbt_migrate/issues/65))
* BT_backup auto-detection follows qBittorrent's own resolution order, including
  `XDG_DATA_HOME` and the correct macOS location. ([#71](https://github.com/jslay88/qbt_migrate/issues/71))
* The Docker entrypoint quotes its arguments, so paths containing spaces are no
  longer split
* A fastresume with no path keys is rejected instead of having the literal
  string `"None"` written as its save path
* Backup zip entries are flat rather than nested under the full host path
* `discover_bt_backup_path()` no longer raises `TypeError` when `HOME` or
  `LOCALAPPDATA` is unset
* `pip install .`, `pip install -e .`, and `pip install git+...` work again.
  They had been failing since 2.3.2 with `ModuleNotFoundError: No module named
  'qbt_migrate'`.
* Discovery processes files in sorted order, so output is reproducible

Added:

* `-z` / `--skip-backup` to skip the backup archive, useful when making a series
  of path changes over a large library
  ([#76](https://github.com/jslay88/qbt_migrate/pull/76), thanks @lvldesigner)
* `max_workers` on `QBTBatchMove.run()`
* `py.typed`, so type information actually reaches consumers
* `QBTMigrateError` and `FastResumeUpdateError` in the public API
* Docker images for `linux/arm64` alongside `amd64`
* [docs/paths.md](docs/paths.md) covering escaping, separators, and trailing
  slashes

Internal:

* ruff replaces black and isort, mypy runs `strict = true`, bandit and actionlint
  in the lint gate
* Branch coverage measured and enforced at 100%
* Test suite no longer depends on the working directory or on pytest's own argv
* Workflows moved off shut-down artifact actions, matrix runs 3.10 to 3.14 with
  `fail-fast: false`, QA also runs on pushes to master
* Releases publish through PyPI Trusted Publishing with attestations
* Dependabot configuration added

## 2.3.2 and earlier

See the [releases page](https://github.com/jslay88/qbt_migrate/releases).
