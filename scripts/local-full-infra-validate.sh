#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '[asf-local-validate] %s\n' "$*"
}

die() {
  printf '[asf-local-validate] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    die "$name is required for full-infra validation"
  fi
}

require_llm_upstream_env() {
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    die "OPENROUTER_API_KEY or OPENAI_API_KEY is required for full-infra validation"
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

http_json_field() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local deadline=$((SECONDS + 180))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name is healthy"
      return 0
    fi
    sleep 3
  done
  die "$name is not healthy at $url"
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

check_sse_once() {
  local run_id="$1"
  python3 - "$ASF_TEST_API_BASE_URL/runs/$run_id/stream" "$ASF_TEST_BEARER_TOKEN" "$ASF_TEST_TENANT_ID" <<'PY'
import sys
import time
import urllib.request

url, token, tenant_id = sys.argv[1:4]
request = urllib.request.Request(
    url,
    headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id},
)
deadline = time.time() + 30
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        while time.time() < deadline:
            line = response.readline()
            if line.startswith(b"data:"):
                sys.exit(0)
except Exception as exc:
    print(f"SSE check failed: {exc}", file=sys.stderr)
sys.exit(1)
PY
}

wait_for_run_evidence() {
  local run_id="$1"
  local deadline=$((SECONDS + ${ASF_VALIDATE_RUN_TIMEOUT_SECONDS:-900}))
  local model_calls=0
  local agent_states=0
  local sandbox_executions=0
  local test_reports=0
  local gates=0
  local status=""
  local hrs=0
  local package_status=0

  while [ "$SECONDS" -lt "$deadline" ]; do
    run_json="$(api_get "/runs/$run_id")"
    status="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
    hrs="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("homologation_readiness_score") or 0)')"
    model_calls="$(api_get "/runs/$run_id/model-calls" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    agent_states="$(api_get "/runs/$run_id/agent-states" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    sandbox_executions="$(api_get "/runs/$run_id/sandbox-executions" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    test_reports="$(api_get "/runs/$run_id/test-reports" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    gates="$(api_get "/runs/$run_id/quality-gates" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    package_status="$(api_status "/runs/$run_id/delivery-package")"

    log "run=$run_id status=$status hrs=$hrs agents=$agent_states model_calls=$model_calls sandbox=$sandbox_executions tests=$test_reports gates=$gates package_http=$package_status"
    if [ "$agent_states" -ge 5 ] \
      && [ "$model_calls" -ge 1 ] \
      && [ "$sandbox_executions" -ge 2 ] \
      && [ "$test_reports" -ge 2 ] \
      && [ "$gates" -ge 17 ] \
      && [ "$package_status" = "200" ] \
      && python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) >= 90 else 1)' "$hrs"; then
      api_get "/runs/$run_id/files" | python3 -c 'import json,sys; files=json.load(sys.stdin); assert any(str(row.get("file_path","")).startswith("generated_app/") for row in files)'
      return 0
    fi
    sleep 10
  done

  die "Enterprise run did not produce required evidence before timeout"
}

main() {
  load_env_file "$REPO_ROOT/.env"

  require_cmd curl
  require_cmd python3
  require_cmd docker
  require_cmd kubectl
  require_cmd kind
  require_llm_upstream_env
  require_env ASF_LITELLM_API_KEY

  log "Validating Docker Compose configuration"
  (cd "$REPO_ROOT" && docker compose config >/dev/null)

  export ASF_TEST_API_BASE_URL="${ASF_TEST_API_BASE_URL:-http://localhost:8000}"
  export ASF_TEST_TENANT_ID="${ASF_TEST_TENANT_ID:-local-dev}"
  local keycloak_user="${ASF_LOCAL_KEYCLOAK_USER:-operator@local.dev}"
  local keycloak_password="${ASF_LOCAL_KEYCLOAK_PASSWORD:-ChangeMe123!}"

  wait_for_http "API" "$ASF_TEST_API_BASE_URL/health"
  wait_for_http "Web" "http://localhost:3000"
  wait_for_http "Temporal UI" "http://localhost:8080"
  wait_for_http "Keycloak" "http://localhost:8081/realms/software-factory/.well-known/openid-configuration"
  wait_for_http "MinIO" "http://localhost:9000/minio/health/ready"
  wait_for_http "LiteLLM" "http://localhost:4000/health/liveliness"

  log "Getting real OIDC token from Keycloak for $keycloak_user"
  token_json="$(
    curl -fsS -X POST "http://localhost:8081/realms/software-factory/protocol/openid-connect/token" \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode 'client_id=software-factory-web' \
      --data-urlencode 'grant_type=password' \
      --data-urlencode "username=$keycloak_user" \
      --data-urlencode "password=$keycloak_password"
  )"
  export ASF_TEST_BEARER_TOKEN="$(printf '%s' "$token_json" | http_json_field access_token)"
  mkdir -p "$REPO_ROOT/data"
  {
    printf 'export ASF_TEST_API_BASE_URL=%q\n' "$ASF_TEST_API_BASE_URL"
    printf 'export ASF_TEST_TENANT_ID=%q\n' "$ASF_TEST_TENANT_ID"
    printf 'export ASF_TEST_BEARER_TOKEN=%q\n' "$ASF_TEST_BEARER_TOKEN"
  } > "$REPO_ROOT/data/local-full-infra-test.env"

  log "Checking authenticated principal"
  api_get "/auth/me" >/dev/null

  if command -v kind >/dev/null 2>&1; then
    kubectl --context "kind-${KIND_CLUSTER_NAME:-asf-local}" -n software-factory-sandbox get networkpolicy sandbox-deny-all >/dev/null
    kubectl --context "kind-${KIND_CLUSTER_NAME:-asf-local}" -n software-factory-sandbox get pvc "${ASF_SANDBOX_WORKSPACE_PVC:-asf-sandbox-workspaces}" >/dev/null
  fi

  log "Running backend production-stack tests inside the API container"
  (cd "$REPO_ROOT" && docker compose exec -T \
    -e ASF_TEST_API_BASE_URL="http://api:8000" \
    -e ASF_TEST_BEARER_TOKEN="$ASF_TEST_BEARER_TOKEN" \
    -e ASF_TEST_TENANT_ID="$ASF_TEST_TENANT_ID" \
    api python -m pytest)

  if [ "${ASF_VALIDATE_ENTERPRISE_RUN:-1}" = "1" ]; then
    log "Starting real enterprise build through API"
    run_payload='{"prompt":"Crie uma plataforma enterprise com RBAC, auditoria, SLA, aprovação humana, qualidade de release e integração ERP.","project_name":"Local Full Infra Validation","template":"enterprise-saas","industry":"financial_services","quality_profile":"regulated_enterprise","compliance":["SOC2","LGPD","ISO27001"],"integrations":["SSO/OIDC","ERP","Data Warehouse"],"data_sensitivity":"confidential"}'
    run_json="$(api_post_json "/runs/enterprise" "$run_payload")"
    run_id="$(printf '%s' "$run_json" | http_json_field id)"
    log "Run created: $run_id"
    check_sse_once "$run_id"
    wait_for_run_evidence "$run_id"
    export ASF_TEST_COMPLETED_RUN_ID="$run_id"
  fi

  log "Creating real batch through API"
  batch_json="$(api_post_json "/batches" '{}')"
  batch_id="$(printf '%s' "$batch_json" | http_json_field id)"
  test "$(api_get "/batches/$batch_id/items" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')" -eq 3
  api_get "/batches/$batch_id/metrics" >/dev/null

  log "Building frontend through Docker Compose"
  (cd "$REPO_ROOT" && docker compose build web)

  if [ "${ASF_VALIDATE_PLAYWRIGHT:-1}" = "1" ]; then
    log "Running Playwright in Docker against the Compose network"
    (cd "$REPO_ROOT" && docker compose --profile test build web-test web-e2e)
    (cd "$REPO_ROOT" && docker compose --profile test run --rm \
      -e ASF_TEST_BEARER_TOKEN="$ASF_TEST_BEARER_TOKEN" \
      -e ASF_TEST_TENANT_ID="$ASF_TEST_TENANT_ID" \
      web-e2e)
    (cd "$REPO_ROOT" && docker compose --profile test stop web-test >/dev/null 2>&1 || true)
  fi

  log "Full-infra validation completed"
}

main "$@"
