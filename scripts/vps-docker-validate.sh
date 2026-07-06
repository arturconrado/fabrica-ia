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

main() {
  load_env_file "$REPO_ROOT/.env.vps"

  require_cmd curl
  require_cmd python3
  require_cmd docker
  require_cmd kubectl
  require_cmd kind

  require_llm_upstream_env
  for name in ASF_API_DOMAIN ASF_AUTH_DOMAIN ASF_PUBLIC_DOMAIN ASF_LITELLM_API_KEY; do
    require_env "$name"
  done

  export ASF_TEST_API_BASE_URL="${ASF_TEST_API_BASE_URL:-https://$ASF_API_DOMAIN}"
  export ASF_TEST_TENANT_ID="${ASF_TEST_TENANT_ID:-${ASF_DEFAULT_TENANT_ID:-production}}"
  local keycloak_user="${ASF_VPS_KEYCLOAK_USER:-operator@local.dev}"
  local keycloak_password="${ASF_VPS_KEYCLOAK_PASSWORD:-ChangeMe123!}"

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

  log "Starting enterprise run through public API"
  run_payload='{"prompt":"Crie uma plataforma enterprise com RBAC, auditoria, SLA, aprovação humana, qualidade de release e integração ERP.","project_name":"VPS Production Docker Validation","template":"enterprise-saas","industry":"financial_services","quality_profile":"regulated_enterprise","compliance":["SOC2","LGPD","ISO27001"],"integrations":["SSO/OIDC","ERP","Data Warehouse"],"data_sensitivity":"confidential"}'
  run_json="$(api_post_json "/runs/enterprise" "$run_payload")"
  run_id="$(printf '%s' "$run_json" | json_field id)"
  log "Run created: $run_id"

  deadline=$((SECONDS + ${ASF_VALIDATE_RUN_TIMEOUT_SECONDS:-900}))
  while [ "$SECONDS" -lt "$deadline" ]; do
    run_state="$(api_get "/runs/$run_id")"
    hrs="$(printf '%s' "$run_state" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("homologation_readiness_score") or 0)')"
    gates="$(api_get "/runs/$run_id/quality-gates" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    sandbox="$(api_get "/runs/$run_id/sandbox-executions" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    tests="$(api_get "/runs/$run_id/test-reports" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    log "run=$run_id hrs=$hrs gates=$gates sandbox=$sandbox tests=$tests"
    if [ "$gates" -ge 17 ] && [ "$sandbox" -ge 2 ] && [ "$tests" -ge 2 ] \
      && python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) >= 90 else 1)' "$hrs"; then
      api_get "/runs/$run_id/delivery-package" >/dev/null
      break
    fi
    sleep 10
  done

  log "Creating production batch through public API"
  batch_json="$(api_post_json "/batches" '{}')"
  batch_id="$(printf '%s' "$batch_json" | json_field id)"
  test "$(api_get "/batches/$batch_id/items" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')" -eq 3
  api_get "/batches/$batch_id/metrics" >/dev/null

  log "Running backend production-stack tests inside API container"
  docker compose -f "$COMPOSE_FILE" exec -T \
    -e ASF_TEST_API_BASE_URL="http://api:8000" \
    -e ASF_TEST_BEARER_TOKEN="$ASF_TEST_BEARER_TOKEN" \
    -e ASF_TEST_TENANT_ID="$ASF_TEST_TENANT_ID" \
    api python -m pytest

  log "VPS Docker validation completed"
}

main "$@"
