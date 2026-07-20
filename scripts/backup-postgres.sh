#!/bin/sh
set -eu

backup_dir="${ASF_BACKUP_DIR:-/backups}"
retention_days="${ASF_BACKUP_RETENTION_DAYS:-7}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_name="${ASF_BACKUP_NAME:-factory}"
target="${backup_dir}/${backup_name}-${timestamp}.dump"
temporary="${target}.partial"

mkdir -p "${backup_dir}"
pg_dump --format=custom --no-owner --no-privileges --file="${temporary}"
pg_restore --list "${temporary}" >/dev/null
mv "${temporary}" "${target}"
find "${backup_dir}" -type f -name "${backup_name}-*.dump" -mtime "+${retention_days}" -delete
find "${backup_dir}" -type f -name "${backup_name}-*.dump.sha256" -mtime "+${retention_days}" -delete
sha256sum "${target}" > "${target}.sha256"
echo "backup_created=${target}"
