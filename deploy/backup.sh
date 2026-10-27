#!/bin/sh
set -eu
umask 077

project=/opt/itlive23bot
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$project/backups"
PYTHONPATH="$project" /usr/bin/python3 -m itlive.backup create \
  "$project/data/itlive.sqlite3" \
  "$project/backups/itlive-$stamp.sqlite3"
