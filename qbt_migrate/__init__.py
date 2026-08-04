"""qBt Migrate, change the paths of existing torrents in qBittorrent, as well as convert paths to Windows/Linux/Mac"""

import logging

from qbt_migrate.classes import FastResume, QBTBatchMove
from qbt_migrate.methods import convert_slashes, discover_bt_backup_path


# Must stay a plain string literal so flit can read it without importing the
# package. Pre-release builds rewrite this line rather than appending at import
# time; see the TestPyPI step in .github/workflows/python.yml.
__version__ = "2.3.2"

logging.getLogger(__name__).addHandler(logging.NullHandler())
