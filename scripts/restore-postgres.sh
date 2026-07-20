#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: restore-postgres.sh /backups/factory-YYYYmmddTHHMMSSZ.dump" >&2
  exit 2
fi

backup="$1"
test -f "${backup}"
checksum_file="${backup}.sha256"
test -f "${checksum_file}"
expected="$(cut -d ' ' -f 1 "${checksum_file}")"
actual="$(sha256sum "${backup}" | cut -d ' ' -f 1)"
test "${expected}" = "${actual}"
pg_restore --list "${backup}" >/dev/null
pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname="${PGDATABASE:-factory}" "${backup}"
echo "restore_completed=${backup}"
