import logging
import argparse

from . import QBTBatchMove, discover_bt_backup_path


logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--existing-path', help='Existing root of path to look for.')
    parser.add_argument('-n', '--new-path', help='New root path to replace existing root path with.')
    parser.add_argument('-t', '--target-os', help='Target OS (converts slashes). '
                                                  'Default is to not change existing Target OS.',
                        choices=['Windows', 'Linux', 'Mac'])
    parser.add_argument('-b', '--bt-backup-path', help='BT_Backup Path Override. Default is %s'
                                                       % discover_bt_backup_path())

    parser.add_argument('-l', '--log-level', help='Log Level, Default is INFO.',
                        choices=['DEBUG', 'INFO'], default='INFO')

    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig()
    logger.setLevel(args.log_level)
    logging.getLogger('qbt_migrate').setLevel(args.log_level)
    logging.getLogger('qbt_migrate').propagate = True
    qbm = QBTBatchMove()
    if args.bt_backup_path is not None:
        qbm.bt_backup_path = args.bt_backup_path
    else:
        bt_backup_path = input('BT_Backup Path (%s): ' % qbm.bt_backup_path)
        if bt_backup_path.strip():
            qbm.bt_backup_path = bt_backup_path
    if args.existing_path is None:
        args.existing_path = input('Existing Path: ')
    if args.new_path is None:
        args.new_path = input('New Path: ')
    if args.target_os is None:
        args.target_os = input('Target OS (Windows, Linux, Mac, Blank for same as existing): ')
    if args.target_os.strip() and args.target_os.lower() not in ('windows', 'linux', 'mac'):
        raise ValueError('Target OS is not valid. Must be Windows, Linux, or Mac. Received: %s' % args.target_os)
    elif not args.target_os.strip():
        args.target_os = None
    qbm.run(args.existing_path, args.new_path, args.target_os)


if __name__ == '__main__':
    main()
