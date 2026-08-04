# Paths, separators, and trailing slashes

Nearly every bug report against this tool has come back to one of the three
things on this page. Read it before opening an issue about paths not being
replaced.

## Shell escaping is not our problem

On Linux and Mac, `\` is the shell's escape character. When you type:

```
qbt_migrate -e X:\ -n /torrents/
```

your shell hands `qbt_migrate` the string `X:` because `\ ` escaped the space.
You have to double it:

```
qbt_migrate -e X:\\ -n /torrents/
```

Or single-quote it, which is easier to get right:

```
qbt_migrate -e 'X:\' -n /torrents/
```

`qbt_migrate` never sees what you typed, only what the shell passed it, so this
cannot be worked around inside the tool. Run with `-l DEBUG` and check the
`Existing Path:` line if you are unsure what actually arrived.

On Windows `cmd` and PowerShell do not treat `\` this way, so a single one is
fine there.

## Separators are matched both ways

qBittorrent writes `save_path`, `qBt-savePath`, and `qBt-downloadPath` using
the separators of whatever platform wrote the file. A library that has moved
between machines can have a mix, sometimes within a single `.fastresume`.

You do not need to care. `qbt_migrate` matches your pattern against both
conventions, so `-e 'S:\'` and `-e 'S:/'` find the same files and produce the
same result. This was not true before 3.0, which is why older reports mention
needing several passes ([#75](https://github.com/jslay88/qbt_migrate/issues/75)).

The replacement is idempotent. Running the same command twice changes nothing
the second time. If a second run does find work, that is a bug worth reporting.

## Trailing slashes are yours to get right

Replacement is a plain substring swap. The tool does not add or remove
separators at the join, so the trailing slash has to match on both sides.

| Command | `X:\Torrents\movie` becomes | |
| --- | --- | --- |
| `-e 'X:\' -n /torrents` | `/torrentsTorrents/movie` | wrong |
| `-e 'X:\' -n /torrents/` | `/torrents/Torrents/movie` | ok |
| `-e 'X:' -n /torrents` | `/torrents/Torrents/movie` | ok |
| `-e 'X:\Torrents' -n /torrents` | `/torrents/movie` | ok |

Either put a trailing separator on both, or on neither.

## Regex mode is a separate contract

With `-r` / `--regex`, your pattern goes to `re.sub` untouched. Separators are
**not** matched both ways, because `\` is an escape character in a regular
expression and rewriting it would corrupt sequences like `\w` or `\d`.

If you need to match a Windows path in regex mode, escape the separators
yourself:

```
qbt_migrate -r -e 'X:\\\\(\w+)' -n '/mnt/x/\1'
```

Capture groups are recommended so you are not throwing away the rest of the
path.

## Check first

`--dry-run` prints what each key would become, per file, and writes nothing. Use
it whenever you are unsure about a pattern, particularly the trailing separator:

```
$ qbt_migrate -e 'X:\' -n /torrents --dry-run
    save_path         'X:\Torrents\movie' -> '/torrentsTorrents/movie'

$ qbt_migrate -e 'X:\' -n /torrents/ --dry-run
    save_path         'X:\Torrents\movie' -> '/torrents/Torrents/movie'
```

The values are quoted so you can see leading and trailing separators, which is
where this usually goes wrong.

## Before you run it

* Fully exit qBittorrent. `File` -> `Exit`, the tray icon, or the task manager.
  Closing the window is not enough on Windows, and a running client will
  rewrite the files back out from memory. `qbt_migrate` checks for this and will
  offer to stop it, but detection cannot see the host from inside a container.
* A backup zip is written into `BT_backup` unless you pass `-z`. Keep it until
  you have confirmed the library is seeding.
* Run with `-l DEBUG` first if you want to see what would be matched, path by
  path.
