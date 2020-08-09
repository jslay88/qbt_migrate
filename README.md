# qBt Migrate


This tool changes the root paths of existing torrents in qBittorrent.
It can also convert slashes when migrating between Windows and Linux/Mac.


## Usage

Install from PyPi using `pip`

    pip install qbt-migrate
    
    
Run the script and follow prompts or use CLI arguments with command `qbt_migrate`

    usage: qbt_migrate [-h] [-e EXISTING_PATH] [-n NEW_PATH] [-t {Windows,Linux,Mac}]
              [-b BT_BACKUP_PATH] [-l {DEBUG,INFO}]
    
    optional arguments:
      -h, --help            show this help message and exit
      -e EXISTING_PATH, --existing-path EXISTING_PATH
                            Existing root of path to look for.
      -n NEW_PATH, --new-path NEW_PATH
                            New root path to replace existing root path with.
      -t {Windows,Linux,Mac}, --target-os {Windows,Linux,Mac}
                            Target OS (converts slashes). Default is to not change
                            existing Target OS.
      -b BT_BACKUP_PATH, --bt-backup-path BT_BACKUP_PATH
                            BT_Backup Path Override. 
      -l {DEBUG,INFO}, --log-level {DEBUG,INFO}
                            Log Level, Default is INFO.


By default, everything happens in the BT_Backup directory defined by the OS the script is running on.
Override `BT_Backup` path if needed.

Default BT_Backup paths:
* Windows: `%LOCALAPPDATA%/qBittorrent/BT_Backup`
* Linux/Mac: `$HOME/.local/share/data/qBittorrent/BT_backup`

A backup zip archive is automatically created in the directory that contains
the `BT_Backup` directory. Default, for instance, would be the `qBittorrent` directory mentioned above.

### Examples
Assuming all of our torrents are in `X:\Torrents` when coming from Windows, or `/torrents` when coming from Linux/Mac

    qbt_migrate -e X:\ -n Z:\ -t Windows  # Windows to Windows (Drive letter change)
    qbt_migrate -e X:\Torrents -n X:\NewDir\Torrents -t Windows  # Windows to Windows (Directory Change)
    qbt_migrate -e X:\Torrents -n Z:\NewDir\Torrents -t Windows  # Windows to Windows (Drive letter change with directory change)
    qbt_migrate -e X:\Torrents -n /torrents -t Linux  # Windows to Linux/Mac (converts slashes)
    
    qbt_migrate -e /torrents -n /new/path/for/torrents  # Changes torrent root path on Linux/Mac
    qbt_migrate -e /torrents -n Z:\Torrents -t Windows  # Linux/Mac to Windows (converts slashes)
