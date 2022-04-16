"""qBt Migrate, change the paths of existing torrents in qBittorrent, as well as convert paths to Windows/Linux/Mac"""
import logging
import os

from .classes import FastResume, QBTBatchMove
from .methods import convert_slashes, discover_bt_backup_path


__version__ = "2.2.0" + os.getenv("VERSION_TAG", "")

logging.getLogger(__name__).addHandler(logging.NullHandler())
