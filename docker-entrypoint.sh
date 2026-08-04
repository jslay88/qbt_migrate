#!/bin/sh
set -eu

# Quoted. The generated entrypoint this replaced used a bare `$@`, so any
# argument containing a space was split by the shell:
#   -n '/new path/here'  ->  qbt_migrate: error: unrecognized arguments: path/here
exec qbt_migrate -b "$BT_BACKUP_PATH" "$@"
