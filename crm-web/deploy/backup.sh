#!/usr/bin/env bash
set -euo pipefail
cd /opt/itlive-crm-web
install -d -m 0700 backups
stamp=$(date -u +%Y-%m-%dT%H-%M-%SZ)
target="backups/itlive-crm-$stamp.sql.gz"
temp="$target.tmp"
docker compose exec -T db pg_dump -U itlive -d itlive --no-owner --no-acl | gzip -9 > "$temp"
gzip -t "$temp"
chmod 0600 "$temp"
mv "$temp" "$target"
echo "Backup ready: $target"
