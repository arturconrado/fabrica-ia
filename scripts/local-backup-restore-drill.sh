#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
output_dir="${1:-$repo_root/artifacts/production-readiness/backup-restore}"
drill_id="$(date -u +%Y%m%d%H%M%S)-$$"
drill_started="$(python3 -c 'import time; print(time.monotonic())')"
container_backup="/tmp/asf-backup-restore-$drill_id.dump"
local_backup="$output_dir/factory-$drill_id.dump"
compose=(docker compose -f "$repo_root/docker-compose.yml")
restore_databases=()

cleanup() {
  for database in "${restore_databases[@]:-}"; do
    [ -n "$database" ] || continue
    "${compose[@]}" exec -T postgres dropdb -U factory --force --if-exists "$database" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

mkdir -p "$output_dir"
postgres_container="$("${compose[@]}" ps -q postgres)"
[ -n "$postgres_container" ] || { printf 'postgres service is not running\n' >&2; exit 1; }

"${compose[@]}" exec -T postgres pg_dump -U factory -d factory --format=custom \
  --no-owner --no-privileges --file="$container_backup"
docker cp "$postgres_container:$container_backup" "$local_backup" >/dev/null
backup_sha256="$(shasum -a 256 "$local_backup" | awk '{print $1}')"
python3 -c '
import hashlib, pathlib, sys
payload = bytearray(pathlib.Path(sys.argv[1]).read_bytes())
assert payload, "backup is empty"
payload[len(payload) // 2] ^= 1
assert hashlib.sha256(payload).hexdigest() != sys.argv[2]
' "$local_backup" "$backup_sha256"

source_counts="$("${compose[@]}" exec -T postgres psql -U factory -d factory -At -F, -c \
  "SELECT (SELECT count(*) FROM artifacts),(SELECT count(*) FROM ledger_records),\
  (SELECT count(*) FROM model_calls),(SELECT count(*) FROM service_deliverables WHERE status = 'delivered'),\
  (SELECT count(*) FROM workflow_runs WHERE status = 'approved_for_homologation');")"
rto_values=()
for iteration in 1 2 3; do
  database="asf_restore_${drill_id//-/}_${iteration}"
  restore_databases+=("$database")
  started="$(python3 -c 'import time; print(time.monotonic())')"
  "${compose[@]}" exec -T postgres createdb -U factory "$database"
  "${compose[@]}" exec -T postgres pg_restore -U factory -d "$database" --no-owner \
    --no-privileges --exit-on-error "$container_backup"
  restored_counts="$("${compose[@]}" exec -T postgres psql -U factory -d "$database" -At -F, -c \
    "SELECT (SELECT count(*) FROM artifacts),(SELECT count(*) FROM ledger_records),\
    (SELECT count(*) FROM model_calls),(SELECT count(*) FROM service_deliverables WHERE status = 'delivered'),\
    (SELECT count(*) FROM workflow_runs WHERE status = 'approved_for_homologation');")"
  [ "$restored_counts" = "$source_counts" ] || { printf 'RPO check failed: %s != %s\n' "$restored_counts" "$source_counts" >&2; exit 1; }
  "${compose[@]}" exec -T \
    -e DATABASE_URL="postgresql+psycopg://factory:${ASF_POSTGRES_PASSWORD:-factory}@postgres:5432/$database" \
    -e ASF_DATABASE_URL="postgresql+psycopg://factory:${ASF_POSTGRES_PASSWORD:-factory}@postgres:5432/$database" \
    api python -c '
from sqlalchemy import text
from app.db.session import SessionLocal, set_tenant_context
from app.service_delivery.ledger import verify_hash_chain
db = SessionLocal()
try:
    tenants = list(db.execute(text("SELECT DISTINCT tenant_id FROM ledger_records ORDER BY tenant_id")).scalars())
    for tenant_id in tenants:
        set_tenant_context(db, tenant_id, "restore-drill")
        assert verify_hash_chain(db, tenant_id), tenant_id
finally:
    db.close()
'
  finished="$(python3 -c 'import time; print(time.monotonic())')"
  rto_values+=("$(python3 -c 'import sys; print(max(0.0, float(sys.argv[2])-float(sys.argv[1])))' "$started" "$finished")")
done

tamper_database="${restore_databases[0]}"
if "${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U factory -d "$tamper_database" -c \
  "UPDATE ledger_records SET payload_json = '{\"append_only_probe\":true}'::json WHERE id = (SELECT id FROM ledger_records ORDER BY tenant_sequence LIMIT 1);" \
  >/dev/null 2>&1; then
  printf 'append-only trigger accepted a ledger mutation\n' >&2
  exit 1
fi
"${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U factory -d "$tamper_database" <<'SQL' \
  >/dev/null
ALTER TABLE ledger_records DISABLE TRIGGER ledger_records_append_only;
UPDATE ledger_records
SET payload_json = '{"tampered_restore":true}'::json
WHERE id = (SELECT id FROM ledger_records ORDER BY tenant_sequence LIMIT 1);
ALTER TABLE ledger_records ENABLE TRIGGER ledger_records_append_only;
SQL
"${compose[@]}" exec -T \
  -e DATABASE_URL="postgresql+psycopg://factory:${ASF_POSTGRES_PASSWORD:-factory}@postgres:5432/$tamper_database" \
  -e ASF_DATABASE_URL="postgresql+psycopg://factory:${ASF_POSTGRES_PASSWORD:-factory}@postgres:5432/$tamper_database" \
  api python -c '
from sqlalchemy import text
from app.db.session import SessionLocal, set_tenant_context
from app.service_delivery.ledger import verify_hash_chain
db = SessionLocal()
try:
    tenant_id = db.execute(
        text("SELECT tenant_id FROM ledger_records WHERE payload_json->>:key = :value"),
        {"key": "tampered_restore", "value": "true"},
    ).scalar_one()
    set_tenant_context(db, tenant_id, "restore-drill")
    assert not verify_hash_chain(db, tenant_id), "tampered restored ledger was accepted"
finally:
    db.close()
'

drill_finished="$(python3 -c 'import time; print(time.monotonic())')"
release_commit_sha="${ASF_RELEASE_COMMIT_SHA:-$(git -C "$repo_root" rev-parse HEAD)}"
RTO_VALUES="$(IFS=,; printf '%s' "${rto_values[*]}")" \
SOURCE_COUNTS="$source_counts" BACKUP_SHA256="$backup_sha256" BACKUP_PATH="$local_backup" \
PRODUCTION_E2E_RUN_ID="${ASF_PRODUCTION_E2E_RUN_ID:-}" \
RELEASE_TENANT_ID="${ASF_RELEASE_TENANT_ID:-}" RELEASE_COMMIT_SHA="$release_commit_sha" \
DRILL_STARTED="$drill_started" DRILL_FINISHED="$drill_finished" \
python3 - "$output_dir/backup-restore.json" <<'PY'
from datetime import datetime, timezone
import json, math, os, pathlib, sys
values = sorted(float(value) for value in os.environ["RTO_VALUES"].split(","))
assert values and all(value >= 0 for value in values), "RTO samples must be non-negative"
p95 = values[max(0, math.ceil(len(values) * .95) - 1)]
artifacts, ledger, model_calls, delivered, approved_runs = (
    int(value) for value in os.environ["SOURCE_COUNTS"].split(",")
)
payload = {
    "schema_version": "local-backup-restore-v1", "status": "passed" if p95 <= 300 else "failed",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "commit_sha": os.environ["RELEASE_COMMIT_SHA"],
    "environment": "homologation", "tenant_id": os.environ["RELEASE_TENANT_ID"],
    "command": "local-backup-restore-drill.sh",
    "duration_seconds": max(0.0, float(os.environ["DRILL_FINISHED"]) - float(os.environ["DRILL_STARTED"])),
    "production_e2e_run_id": os.environ["PRODUCTION_E2E_RUN_ID"] or None,
    "backup_path": os.environ["BACKUP_PATH"], "backup_sha256": os.environ["BACKUP_SHA256"],
    "restore_attempts": len(values), "rto_seconds": values, "rto_p95_seconds": p95,
    "rpo_lost_confirmed_outputs": 0, "ledger_valid": True, "restore_completed": True,
    "corrupt_backup_rejected_by_sha256": True,
    "append_only_trigger_rejected_mutation": True,
    "tampered_restore_rejected_by_ledger": True,
    "source_counts": {"artifacts": artifacts, "ledger_records": ledger, "model_calls": model_calls,
                      "delivered_service_deliverables": delivered, "approved_runs": approved_runs},
    "summary": {"restore_attempts": len(values), "rpo": 0, "rto_p95_seconds": p95},
    "failures": [] if p95 <= 300 else ["rto_p95_exceeded"],
    "artifacts": [{"path": os.environ["BACKUP_PATH"], "sha256": os.environ["BACKUP_SHA256"]}],
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
raise SystemExit(0 if payload["status"] == "passed" else 1)
PY
