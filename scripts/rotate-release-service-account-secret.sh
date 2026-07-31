#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
output="${1:-$repo_root/artifacts/production-readiness/credential-rotation.json}"

require_env() {
  local name="$1"
  [ -n "${!name:-}" ] || { printf '%s is required\n' "$name" >&2; exit 1; }
}

for name in ASF_NEW_RELEASE_CLIENT_SECRET ASF_RELEASE_TENANT_ID ASF_RELEASE_OPERATOR \
  ASF_PRODUCTION_E2E_RUN_ID ASF_RELEASE_CREDENTIAL_ROTATION_CONFIRM KEYCLOAK_ADMIN \
  KEYCLOAK_ADMIN_PASSWORD; do
  require_env "$name"
done
[ "$ASF_RELEASE_CREDENTIAL_ROTATION_CONFIRM" = "ROTATE_RELEASE_SERVICE_ACCOUNT_SECRET" ] \
  || { printf 'Explicit release credential rotation confirmation is required\n' >&2; exit 1; }
[ "${ASF_LOCAL_RELEASE_CLIENT_SECRET:-}" != "$ASF_NEW_RELEASE_CLIENT_SECRET" ] \
  || { printf 'New release client secret must differ from the current secret\n' >&2; exit 1; }

compose=(docker compose -f "$repo_root/docker-compose.yml" -f "$repo_root/docker-compose.full.yml" --profile full)
"${compose[@]}" exec -T keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user "$KEYCLOAK_ADMIN" \
  --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null
client_id="$("${compose[@]}" exec -T keycloak /opt/keycloak/bin/kcadm.sh get clients \
  -r software-factory -q clientId=software-factory-release --fields id | \
  python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0]["id"] if rows else "")')"
[ -n "$client_id" ] || { printf 'software-factory-release client not found\n' >&2; exit 1; }
"${compose[@]}" exec -T keycloak /opt/keycloak/bin/kcadm.sh update "clients/$client_id" \
  -r software-factory -s secret="$ASF_NEW_RELEASE_CLIENT_SECRET" >/dev/null

mkdir -p "$(dirname "$output")"
ROTATION_OUTPUT="$output" REPO_ROOT="$repo_root" python3 - <<'PY'
from datetime import datetime, timezone
import json, os, pathlib, subprocess

repo = pathlib.Path(os.environ["REPO_ROOT"])
commit = os.environ.get("ASF_RELEASE_COMMIT_SHA") or subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=repo, text=True
).strip()
payload = {
    "schema_version": "release-credential-rotation/1.0",
    "status": "passed",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "commit_sha": commit,
    "environment": "homologation",
    "tenant_id": os.environ["ASF_RELEASE_TENANT_ID"],
    "production_e2e_run_id": os.environ["ASF_PRODUCTION_E2E_RUN_ID"],
    "oauth_client_id": "software-factory-release",
    "operator": os.environ["ASF_RELEASE_OPERATOR"],
    "secret_recorded": False,
    "summary": {"credential_rotated": True, "existing_access_tokens_not_treated_as_rotation_proof": True},
    "failures": [],
    "artifacts": [],
}
pathlib.Path(os.environ["ROTATION_OUTPUT"]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY
printf 'Release service-account secret rotated; no credential was printed or persisted.\n'
