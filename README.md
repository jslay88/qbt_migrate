# qBt Migrate


This tool changes the root paths of existing torrents in qBittorrent.
It can also convert slashes when migrating between Windows and Linux/Mac.


## Usage

Install [Python 3](https://python.org).
Clone the repo
    
    git clone https://github.com/jslay88/qbt_migrate
    
Run the script and follow prompts or use CLI arguments

    usage: cli.py [-h] [-e EXISTING_PATH] [-n NEW_PATH] [-t {Windows,Linux,Mac}]
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


### Examples
Assuming all of our torrents are in `X:\Torrents` when coming from Windows, or `/torrents` when coming from Linux/Mac

    python cli.py -e X:\Torrents -n Z:\Torrents -t Windows  # Windows to Windows (Drive letter change, or directory change, or both)
    python cli.py -e X:\Torrents -n /torrents -t Linux  # Windows to Linux/Mac (converts slashes)
    
    python cli.py -e /torrents -n /new/path/for/torrents  # Changes torrent root path on Linux/Mac
    python cli.py -e /torrents -n Z:\Torrents -t Windows  # Linux/Mac to Windows (converts slashes)
    

    
