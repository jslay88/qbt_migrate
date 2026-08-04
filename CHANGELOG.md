# Changelog

## Unreleased

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
