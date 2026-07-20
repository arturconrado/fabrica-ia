#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.vps.yml"

log() {
  printf '[asf-vps-validate] %s\n' "$*"
}

die() {
  printf '[asf-vps-validate] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    die "$name is required for VPS validation"
  fi
}

require_llm_upstream_env() {
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    die "OPENROUTER_API_KEY or OPENAI_API_KEY is required for VPS validation"
  fi
}

load_env_file() {
  local file="$1"
  if [ ! -f "$file" ]; then
    return 0
  fi
  while IFS='=' read -r key value; do
    case "$key" in
      ""|\#*) continue ;;
    esac
    if [ -z "${!key:-}" ]; then
      export "$key=$value"
    fi
  done < "$file"
}

json_field() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

auth_header() {
  printf 'Authorization: Bearer %s' "$ASF_TEST_BEARER_TOKEN"
}

api_get() {
  curl -fsS -H "$(auth_header)" -H "X-Tenant-ID: $ASF_TEST_TENANT_ID" "$ASF_TEST_API_BASE_URL$1"
}

api_post_json() {
  local path="$1"
  local payload="$2"
  curl -fsS -X POST "$ASF_TEST_API_BASE_URL$path" \
    -H "$(auth_header)" \
    -H "X-Tenant-ID: $ASF_TEST_TENANT_ID" \
    -H 'Content-Type: application/json' \
    -d "$payload"
}

api_status() {
  local path="$1"
  curl -sS -o /dev/null -w '%{http_code}' \
    -H "$(auth_header)" \
    -H "X-Tenant-ID: $ASF_TEST_TENANT_ID" \
    "$ASF_TEST_API_BASE_URL$path" || true
}

validate_observability_pipeline() {
  log "Checking internal Prometheus and Tempo endpoints"
  docker compose -f "$COMPOSE_FILE" exec -T api python -c '
import urllib.request

for url in ("http://prometheus:9090/-/ready", "http://tempo:3200/status/version"):
    with urllib.request.urlopen(url, timeout=10) as response:
        assert response.status == 200
'

  local trace_id
  trace_id="$(docker compose -f "$COMPOSE_FILE" exec -T api python -c '
from app.observability.tracing import configure_tracing, shutdown_tracing, trace_span

assert configure_tracing(service_name="agentic-software-factory-vps-validation")
with trace_span("workflow.run", {"asf.validation": True}) as span:
    print(f"{span.get_span_context().trace_id:032x}")
shutdown_tracing()
')"
  if ! printf '%s' "$trace_id" | grep -Eq '^[0-9a-f]{32}$'; then
    die "OpenTelemetry smoke did not return a valid trace id"
  fi

  local deadline=$((SECONDS + 60))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if docker compose -f "$COMPOSE_FILE" exec -T \
      -e ASF_VALIDATION_TRACE_ID="$trace_id" api python -c '
import os
import urllib.request

trace_id = os.environ["ASF_VALIDATION_TRACE_ID"]
with urllib.request.urlopen(f"http://tempo:3200/api/traces/{trace_id}", timeout=5) as response:
    assert response.status == 200
' >/dev/null 2>&1; then
      log "OpenTelemetry Collector and Tempo persisted validation trace $trace_id"
      return 0
    fi
    sleep 2
  done
  die "Validation trace $trace_id did not reach Tempo through the OpenTelemetry Collector"
}

wait_for_ai_native_evidence() {
  local run_id="$1"
  local deadline=$((SECONDS + ${ASF_VALIDATE_RUN_TIMEOUT_SECONDS:-900}))
  local status=""

  while [ "$SECONDS" -lt "$deadline" ]; do
    local run_state hrs gates model_calls sandbox tests manifest_valid package_status
    run_state="$(api_get "/runs/$run_id")"
    hrs="$(printf '%s' "$run_state" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("homologation_readiness_score") or 0)')"
    status="$(printf '%s' "$run_state" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status") or "")')"
    gates="$(api_get "/runs/$run_id/quality-gates" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    model_calls="$(api_get "/runs/$run_id/model-calls" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    sandbox="$(api_get "/runs/$run_id/sandbox-executions" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    tests="$(api_get "/runs/$run_id/test-reports" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    manifest_valid="$(api_get "/runs/$run_id/validation-manifest" | python3 -c 'import json,sys; row=json.load(sys.stdin); inv=row.get("invariants",{}); ok=bool(inv) and all(inv.values()) and row.get("workflow_id")=="software_factory_ai_native_v2" and row.get("generation_mode")=="ai_native_v2" and 0 < float(row.get("budget",{}).get("actual_usd") or 0) <= 15; print(1 if ok else 0)')"
    package_status="$(api_status "/runs/$run_id/delivery-package")"
    log "run=$run_id status=$status hrs=$hrs model_calls=$model_calls sandbox=$sandbox tests=$tests gates=$gates manifest_valid=$manifest_valid package_http=$package_status"

    if [ "$status" = "failed" ] || [ "$status" = "cancelled" ]; then
      die "AI-native run $run_id ended in terminal status '$status'"
    fi
    if [ "$model_calls" -ge 18 ] \
      && [ "$sandbox" -ge 7 ] \
      && [ "$tests" -ge 7 ] \
      && [ "$gates" -eq 17 ] \
      && [ "$manifest_valid" -eq 1 ] \
      && [ "$status" = "waiting_for_human" ] \
      && [ "$package_status" = "200" ] \
      && python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) >= 85 else 1)' "$hrs"; then
      api_get "/runs/$run_id/validation-manifest" | python3 -c 'import json,sys; row=json.load(sys.stdin); reports=row["test_reports"]; steps=row["steps"]; failed=any(item["status"]=="failed" for item in reports); assert not failed or max(item["iteration"] for item in steps if item["node_id"]=="Engineer") >= 2; assert row["generation_fingerprint"]; assert row["generated_files"]'
      api_get "/runs/$run_id/delivery-package" | python3 -c 'import json,sys; row=json.load(sys.stdin); assert row.get("path", "").startswith("s3://"); assert row.get("manifest_json", {}).get("storage_prefix", "").startswith("tenants/")'
      api_get "/runs/$run_id/delivery-package/download" | python3 -c 'import io,sys,zipfile; archive=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())); assert "manifest.json" in archive.namelist()'
      return 0
    fi
    sleep 10
  done

  die "AI-native run $run_id did not produce the required evidence before timeout"
}

main() {
  load_env_file "$REPO_ROOT/.env.vps"

  require_cmd curl
  require_cmd python3
  require_cmd docker
  require_cmd kubectl
  require_cmd kind

  require_llm_upstream_env
  for name in ASF_API_DOMAIN ASF_AUTH_DOMAIN ASF_PUBLIC_DOMAIN ASF_LITELLM_API_KEY ASF_VPS_KEYCLOAK_USER ASF_VPS_KEYCLOAK_PASSWORD; do
    require_env "$name"
  done

  export ASF_TEST_API_BASE_URL="${ASF_TEST_API_BASE_URL:-https://$ASF_API_DOMAIN}"
  export ASF_TEST_TENANT_ID="${ASF_TEST_TENANT_ID:-${ASF_DEFAULT_TENANT_ID:-production}}"
  local keycloak_user="$ASF_VPS_KEYCLOAK_USER"
  local keycloak_password="$ASF_VPS_KEYCLOAK_PASSWORD"

  log "Validating VPS Compose and public health"
  docker compose -f "$COMPOSE_FILE" config >/dev/null
  curl -fsS "$ASF_TEST_API_BASE_URL/health" >/dev/null
  curl -fsS "https://$ASF_PUBLIC_DOMAIN" >/dev/null
  kubectl --context "kind-${KIND_CLUSTER_NAME:-asf-vps}" -n software-factory-sandbox get networkpolicy sandbox-deny-all >/dev/null
  kubectl --context "kind-${KIND_CLUSTER_NAME:-asf-vps}" -n software-factory-sandbox get pvc "${ASF_SANDBOX_WORKSPACE_PVC:-asf-sandbox-workspaces}" >/dev/null

  log "Getting OIDC token from public Keycloak"
  token_json="$(
    curl -fsS -X POST "https://$ASF_AUTH_DOMAIN/realms/software-factory/protocol/openid-connect/token" \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode 'client_id=software-factory-web' \
      --data-urlencode 'grant_type=password' \
      --data-urlencode "username=$keycloak_user" \
      --data-urlencode "password=$keycloak_password"
  )"
  export ASF_TEST_BEARER_TOKEN="$(printf '%s' "$token_json" | json_field access_token)"

  log "Checking authenticated API"
  api_get "/auth/me" >/dev/null
  validate_observability_pipeline

  log "Starting ContractFlow through the contracted AI-native journey"
  contract_json="$(ASF_VALIDATION_MISSION=contractflow ASF_VALIDATION_OUTPUT=json python3 "$REPO_ROOT/scripts/create-contracted-reference-run.py")"
  contract_run_id="$(printf '%s' "$contract_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')"
  contract_proposal_hash="$(printf '%s' "$contract_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["proposal_sha256"])')"
  wait_for_ai_native_evidence "$contract_run_id"
  approved_json="$(api_post_json "/runs/$contract_run_id/approve" '{"comment":"Validação humana VPS: ContractFlow, evidências, rastreabilidade e pacote revisados e aceitos."}')"
  printf '%s' "$approved_json" | python3 -c 'import json,sys; row=json.load(sys.stdin); assert row.get("status") == "approved_for_homologation"; assert float(row.get("homologation_readiness_score") or 0) == 100'
  contract_fingerprint="$(api_get "/runs/$contract_run_id/validation-manifest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["generation_fingerprint"])')"

  log "Starting ServiceDesk through the contracted AI-native journey"
  servicedesk_json="$(ASF_VALIDATION_MISSION=servicedesk ASF_VALIDATION_OUTPUT=json python3 "$REPO_ROOT/scripts/create-contracted-reference-run.py")"
  servicedesk_run_id="$(printf '%s' "$servicedesk_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')"
  servicedesk_proposal_hash="$(printf '%s' "$servicedesk_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["proposal_sha256"])')"
  wait_for_ai_native_evidence "$servicedesk_run_id"
  approved_json="$(api_post_json "/runs/$servicedesk_run_id/approve" '{"comment":"Validação humana VPS: ServiceDesk, evidências, rastreabilidade e pacote revisados e aceitos."}')"
  printf '%s' "$approved_json" | python3 -c 'import json,sys; row=json.load(sys.stdin); assert row.get("status") == "approved_for_homologation"; assert float(row.get("homologation_readiness_score") or 0) == 100'
  servicedesk_fingerprint="$(api_get "/runs/$servicedesk_run_id/validation-manifest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["generation_fingerprint"])')"

  python3 -c 'import sys; assert sys.argv[1] != sys.argv[2], "The two missions produced equivalent source fingerprints"; assert sys.argv[3] != sys.argv[4], "The two missions produced equivalent proposals"' "$contract_fingerprint" "$servicedesk_fingerprint" "$contract_proposal_hash" "$servicedesk_proposal_hash"

  log "Validating local/offsite backup evidence and Temporal outbox metrics"
  api_get "/metrics" | python3 -c '
import re, sys
text = sys.stdin.read()
rows = dict(re.findall(r"asf_backup_newest_age_seconds\{dataset=\"([^\"]+)\"\} (-?[0-9.]+)", text))
required = {"factory", "temporal", "keycloak", "filesystem", "minio", "offsite"}
assert required.issubset(rows), (required, rows)
assert all(0 <= float(rows[name]) <= 93600 for name in required), rows
attempts = re.search(r"^asf_temporal_outbox_max_attempts ([0-9.]+)$", text, re.M)
oldest = re.search(r"^asf_temporal_outbox_oldest_age_seconds ([0-9.]+)$", text, re.M)
assert attempts and float(attempts.group(1)) < 5, attempts.group(1) if attempts else None
assert oldest and float(oldest.group(1)) < 300, oldest.group(1) if oldest else None
'
  docker compose -f "$COMPOSE_FILE" exec -T backup-offsite /bin/sh -ec '
    test -s /backups/.offsite-last-success
    mc ls --recursive "remote/$ASF_BACKUP_REMOTE_BUCKET/$ASF_BACKUP_REMOTE_PREFIX" | grep -q "\.dump"
    mc ls --recursive "remote/$ASF_BACKUP_REMOTE_BUCKET/$ASF_BACKUP_REMOTE_PREFIX" | grep -q "SHA256SUMS"
  '

  log "Submitting a synthetic alert to the internal Alertmanager"
  docker compose -f "$COMPOSE_FILE" exec -T api python -c '
import datetime, json, urllib.request
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
payload = [{"labels": {"alertname": "AsfDeploymentValidation", "severity": "info"}, "annotations": {"summary": "Synthetic deployment validation alert"}, "startsAt": now}]
request = urllib.request.Request("http://alertmanager:9093/api/v2/alerts", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request, timeout=10) as response:
    assert response.status == 200
'

  log "Running backend production-stack tests inside API container"
  docker compose -f "$COMPOSE_FILE" exec -T \
    -e ASF_TEST_API_BASE_URL="http://api:8000" \
    -e ASF_TEST_BEARER_TOKEN="$ASF_TEST_BEARER_TOKEN" \
    -e ASF_TEST_TENANT_ID="$ASF_TEST_TENANT_ID" \
    -e ASF_TEST_COMPLETED_RUN_ID="$servicedesk_run_id" \
    -e ASF_TEST_CONTRACTFLOW_RUN_ID="$contract_run_id" \
    -e ASF_TEST_SERVICEDESK_RUN_ID="$servicedesk_run_id" \
    -e ASF_TEST_POSTGRES_URL="postgresql+psycopg://factory_app:$ASF_POSTGRES_APP_PASSWORD@postgres:5432/factory" \
    -e ASF_TEST_POSTGRES_ADMIN_URL="postgresql+psycopg://factory:$ASF_POSTGRES_PASSWORD@postgres:5432/factory" \
    api python -m pytest

  log "VPS Docker validation completed"
}

main "$@"
