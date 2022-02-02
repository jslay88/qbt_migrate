import os
import sys
import logging


logger = logging.getLogger(__name__)


def discover_bt_backup_path():
    logger.debug('Discovering BT_backup path...')
    if sys.platform.startswith('linux') and os.path.exists("/.dockerenv"):
        # Default path for config under for image: https://docs.linuxserver.io/images/docker-qbittorrent
        return os.path.join("/config/qBittorrent/BT_backup")
    if sys.platform.startswith('win32'):
        logger.debug('Windows System')
        return os.path.join(os.getenv('localappdata'), 'qBittorrent\\BT_backup')
    logger.debug('Linux/Mac System')
    return os.path.join(os.getenv('HOME'), '.local/share/data/qBittorrent/BT_backup')


def convert_slashes(path: str, target_os: str):
    if target_os.lower() not in ('windows', 'linux', 'mac'):
        raise ValueError('Target OS is not valid. Must be Windows, Linux, or Mac. Received: %s' % target_os)
    if target_os.lower() == 'windows':
        logger.debug('Convert to Windows Slashes')
        return path.replace('/', '\\')
    logger.debug('Convert to Unix Slashes')
    return path.replace('\\', '/')
