# qBt Migrate
![Python QA Checks](https://github.com/jslay88/qbt_migrate/actions/workflows/python.yml/badge.svg)

This tool changes the paths of existing torrents in qBittorrent in a bulk fashion.
It can also convert slashes when migrating between Windows and Linux/Mac.

![Demo](demo.gif)

**Also check out my Chrome Extension for handling TV Episode torrents.**

**qBt TV Torrent Upload**

**[Chrome Web Store](https://chrome.google.com/webstore/detail/qbt-tv-torrent-upload/fhoodbpeaagldkgefdpcnilmjjncihpf)**

**[Source](https://github.com/jslay88/qbt_tv_torrent_uploader)**

## Usage
**ALWAYS** ensure qBittorrent is closed before running `qbt_migrate`.
Either quit through `File` -> `Exit`, task tray icon, or task manager for your system.

Install from PyPi using `pip`, or run with [Docker](#docker).

    pip install qbt_migrate

Run the script and follow prompts or use CLI arguments with command `qbt_migrate`

    usage: qbt_migrate [-h] [-e EXISTING_PATH] [-n NEW_PATH] [-r] [-t {Windows,Linux,Mac}] [-b BT_BACKUP_PATH] [-s] [-z] [-l {DEBUG,INFO}] [-v]

    options:
      -h, --help            show this help message and exit
      -e EXISTING_PATH, --existing-path EXISTING_PATH
                            Existing root of path to look for.
      -n NEW_PATH, --new-path NEW_PATH
                            New root path to replace existing root path with.
      -r, --regex           Existing and New paths are regex patterns. (Capture groups recommended).
      -t {Windows,Linux,Mac}, --target-os {Windows,Linux,Mac}
                            Target OS (converts slashes). Default will auto-detect if conversion is needed based on existing vs new.
      -b BT_BACKUP_PATH, --bt-backup-path BT_BACKUP_PATH
                            BT_backup Path Override.
      -s, --skip-bad-files  Skips bad .fastresume files instead of exiting. Default behavior is to exit.
      -z, --skip-backup     Skips creating a backup zip archive of the BT_backup folder. Default behavior is to create a backup.
      -l {DEBUG,INFO}, --log-level {DEBUG,INFO}
                            Log Level, Default is INFO.
      -v, --version         Prints the current version number and exits.

Anything not passed as an argument is prompted for. When nothing is attached to stdin
(a container without `-it`, cron, a shell script), `qbt_migrate` does not prompt: it uses
the defaults it can (platform `BT_backup` path, no regex, target OS auto-detected) and
exits with a message naming the argument if `-e` or `-n` is missing.

Exit codes: `0` success, `1` one or more `.fastresume` files could not be read or updated,
`2` bad or missing arguments.

By default, everything happens in the BT_backup directory defined by the OS the script is running on.
Override `BT_backup` path if needed.

Default BT_backup paths, checked in this order and matching how qBittorrent itself
resolves them:
* Windows: `%LOCALAPPDATA%\qBittorrent\BT_backup`
* Mac: `$HOME/Library/Application Support/qBittorrent/BT_backup`
* Linux: `$XDG_DATA_HOME/qBittorrent/BT_backup` (`$HOME/.local/share` when unset),
  falling back to the pre-4.x `$XDG_DATA_HOME/data/qBittorrent/BT_backup` when only
  that one exists
* Docker: `/config/qBittorrent/BT_backup`, checked first when running in a container

Run with `-l DEBUG` to see which candidates were checked and which one was picked.

A backup zip archive is automatically created in the `BT_backup` directory. Pass `-z` /
`--skip-backup` to skip it, which is worth doing when you already have one and are making
a series of path changes over a large library, since zipping every run gets slow.

### Examples
Assuming all of our torrents are in `X:\Torrents` when coming from Windows, or `/torrents` when coming from Linux/Mac

**NOTE:** When running `qbt_migrate` on a Linux/Mac machine, Windows paths will require double `\`. Ex. `C:\\Users\\user\\Downloads\\Torrents`

**NOTE:** Take note of trailing slash replacement when changing from Windows <-> Linux. `-e X:\ -n /torrents` will result in `/torrentsxxxxx`, not `/torrents/xxxxx`.
The correct pattern for this would be `-e X: -n /torrents` or `-e X:\ -n /torrents/`.

    qbt_migrate -e X:\ -n Z:\ -t Windows  # Windows to Windows (Drive letter change)
    qbt_migrate -e X:\Torrents -n X:\NewDir\Torrents -t Windows  # Windows to Windows (Directory Change)
    qbt_migrate -e X:\Torrents -n Z:\NewDir\Torrents -t Windows  # Windows to Windows (Drive letter change with directory change)
    qbt_migrate -e X: -n /torrents -t Linux  # Windows to Linux/Mac (converts slashes)  # When running on Linux machine \\ is needed for Windows Paths  # Note Trailing Slash
    qbt_migrate -e X:\Torrents -n /torrents -t Linux  # Windows to Linux/Mac (converts slashes)  # When running on Linux machine \\ is needed for Windows Paths
    qbt_migrate -e X:\\Torrents -n /torrents -t Linux  # Windows to Linux/Mac (converts slashes)  # When running on Linux machine \\ is needed for Windows Paths

    qbt_migrate -e /torrents -n /new/path/for/torrents  # Changes torrent root path on Linux/Mac
    qbt_migrate -e /torrents -n Z:\Torrents -t Windows  # Linux/Mac to Windows (converts slashes)
    qbt_migrate -e /torrents -n Z:\\Torrents -t Windows  # Linux/Mac to Windows (converts slashes)  # When running on Linux machine \\ is needed for Windows Paths

    # Adavanced Usage with RegEx
    # Example would replace /some/test/with/a/path with /test/matched/path
    qbt_migrate -r -e /some/(\w+)/.*$ -n \1/matched/path -t Linux  # Matches using regex patterns and replaces using capture groups.
    qbt_migrate --regex -e /some/(\w+)/.*$ -n \1/matched/path -t Linux  # Matches using regex patterns and replaces using capture groups.

#### Docker
You can also run this tool with Docker if you don't have Python, or don't want to install the package to your system directly.
The BT_backup path is automatically overridden to `/tmp/BT_backup`, so mount your `BT_backup` there.

Images are published for `linux/amd64` and `linux/arm64` to both registries:

* `jslay88/qbt_migrate` (Docker Hub)
* `ghcr.io/jslay88/qbt_migrate` (GitHub Container Registry)

Tags: `latest` and `X.Y.Z` track releases, `master` tracks the default branch.

**NOTE:** When running `qbt_migrate` Docker image on a Linux/Mac machine, Windows paths will require double `\`. Ex. `C:\\Users\\user\\Downloads\\Torrents`

**The Docker image has all functionality as the pip install, following the same arguments/patterns listed in the above examples.**

Add `-it` if you want to be prompted for anything you leave off. Without it, arguments you
omit fall back to their defaults instead of prompting.

For example, mounting in the default BT_backup path on a Windows machine running Docker

    docker run --rm -v %LOCALAPPDATA%/qBittorrent/BT_backup:/tmp/BT_backup jslay88/qbt_migrate -e X:\ -n Z:\  # Windows to Windows (Drive letter change)
    docker run --rm -v %LOCALAPPDATA%/qBittorrent/BT_backup:/tmp/BT_backup jslay88/qbt_migrate -e X:\Torrents -n X:\NewDir\Torrents -t Windows  # Windows to Windows (Directory Change)
    ...

Mounting in the default BT_backup path on a Linux/Mac machine running Docker

    docker run --rm -v $HOME/.local/share/qBittorrent/BT_backup:/tmp/BT_backup jslay88/qbt_migrate -e X:\ -n Z:\  # Windows to Windows (Drive letter change)
    docker run --rm -v $HOME/.local/share/qBittorrent/BT_backup:/tmp/BT_backup jslay88/qbt_migrate -e X:\Torrents -n X:\NewDir\Torrents -t Windows  # Windows to Windows (Directory Change)
    ...

If for some reason you wanted to override BT_backup path from `/tmp/BT_backup` within the container, simply set
environment variable `BT_BACKUP_PATH` on the container to where you will be mounting in.

**The `-e` for environment variable override must go before the image `jslay88/qbt_migrate` as the `-e` after the image is for `--existing-path`**

    docker run --rm -v %LOCALAPPDATA%/qBittorrent/BT_backup:/opt/qbt_migrate/fastresume -e BT_BACKUP_PATH=/opt/qbt_migrate/fastresume jslay88/qbt_migrate -e X:\ -n Z:\  # Windows to Windows (Drive letter change)
    ...

You can also clone this repository, build the image, and run your own built image

    docker build . -t qbt_migrate
    docker run --rm -v %LOCALAPPDATA%/qBittorrent/BT_backup:/tmp/BT_backup qbt_migrate -e X:\ -n Z:\  # Windows to Windows (Drive letter change)
    ...


## Python Module
This project has also been built to be modular and used as a Python Module. If you feel like utilizing this project within your own,
please feel free to do so, and let me know!

Use Cases:
* UI for qbt_migrate
* `FastResume` Class
* Torrent Manager
