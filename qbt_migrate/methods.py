import os
import sys
import logging
import zipfile


logger = logging.getLogger(__name__)


def discover_bt_backup_path():
    logger.debug('Discovering BT_backup path...')
    if sys.platform.startswith('win32'):
        logger.debug('Windows System')
        return os.path.join(os.getenv('localappdata'), 'qBittorrent\\BT_backup')

    if os.path.isfile("/.dockerenv") and os.path.isdir('/config/qBittorrent/BT_backup'):
        # Default path for config under for image: https://docs.linuxserver.io/images/docker-qbittorrent
        logger.debug('qBittorrent Docker container detected')
        return '/config/qBittorrent/BT_backup'

    logger.debug('Linux/Mac System')
    return os.path.join(os.getenv('HOME'), '.local/share/data/qBittorrent/BT_backup')


def convert_slashes(path: str, target_os: str):
    if target_os.strip().lower() not in ('windows', 'linux', 'mac'):
        raise ValueError(f'Target OS is not valid. Must be Windows, Linux, or Mac. Received: {target_os}')
    if target_os.strip().lower() == 'windows':
        logger.debug('Convert to Windows Slashes')
        return path.replace('/', '\\')
    logger.debug('Convert to Unix Slashes')
    return path.replace('\\', '/')


def backup_folder(folder_path: str, archive_path: str):
    logger.info(f'Creating Archive {archive_path} ...')
    with zipfile.ZipFile(archive_path, 'w') as archive:
        for file in os.listdir(folder_path):
            archive.write(os.path.join(folder_path, file))
    logger.info('Done!')
