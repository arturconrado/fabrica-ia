#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export COMPOSE_FILE="$REPO_ROOT/docker-compose.yml:$REPO_ROOT/docker-compose.full.yml"

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

validate_trace_pipeline() {
  local trace_id
  trace_id="$(cd "$REPO_ROOT" && docker compose --profile full exec -T api python -c '
from app.observability.tracing import configure_tracing, shutdown_tracing, trace_span

assert configure_tracing(service_name="agentic-software-factory-validation")
with trace_span("workflow.run", {"asf.validation": True}) as span:
    print(f"{span.get_span_context().trace_id:032x}")
shutdown_tracing()
')"
  if ! printf '%s' "$trace_id" | grep -Eq '^[0-9a-f]{32}$'; then
    die "OpenTelemetry smoke did not return a valid trace id"
  fi

  local deadline=$((SECONDS + 60))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if (cd "$REPO_ROOT" && docker compose --profile full exec -T \
      -e ASF_VALIDATION_TRACE_ID="$trace_id" api python -c '
import os
import urllib.request

trace_id = os.environ["ASF_VALIDATION_TRACE_ID"]
with urllib.request.urlopen(f"http://tempo:3200/api/traces/{trace_id}", timeout=5) as response:
    assert response.status == 200
' >/dev/null 2>&1); then
      log "OpenTelemetry Collector and Tempo persisted validation trace $trace_id"
      return 0
    fi
    sleep 2
  done
  die "Validation trace $trace_id did not reach Tempo through the OpenTelemetry Collector"
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
  local result=1
  set +o pipefail
  if curl -fsSN --max-time 30 \
    -H "$(auth_header)" \
    -H "X-Tenant-ID: $ASF_TEST_TENANT_ID" \
    "$ASF_TEST_API_BASE_URL/runs/$run_id/stream" | grep -qm1 '^data:'; then
    result=0
  fi
  set -o pipefail
  if [ "$result" -ne 0 ]; then
    log "SSE check failed for run $run_id"
    return 1
  fi
}

wait_for_run_evidence() {
  local run_id="$1"
  local deadline=$((SECONDS + ${ASF_VALIDATE_RUN_TIMEOUT_SECONDS:-900}))
  local model_calls=0
  local agent_states=0
  local sandbox_executions=0
  local test_reports=0
  local gates=0
  local manifest_valid=0
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
    manifest_valid="$(api_get "/runs/$run_id/validation-manifest" | python3 -c 'import json,sys; row=json.load(sys.stdin); inv=row.get("invariants",{}); ok=bool(inv) and all(inv.values()) and row.get("workflow_id")=="software_factory_ai_native_v2" and row.get("generation_mode")=="ai_native_v2" and 0 < float(row.get("budget",{}).get("actual_usd") or 0) <= 15; print(1 if ok else 0)')"
    package_status="$(api_status "/runs/$run_id/delivery-package")"

    log "run=$run_id status=$status hrs=$hrs agents=$agent_states model_calls=$model_calls sandbox=$sandbox_executions tests=$test_reports gates=$gates manifest_valid=$manifest_valid package_http=$package_status"
    if [ "$status" = "failed" ] || [ "$status" = "cancelled" ]; then
      die "Enterprise run ended in terminal status '$status' before producing the required evidence"
    fi
    if [ "$agent_states" -ge 5 ] \
      && [ "$model_calls" -ge 18 ] \
      && [ "$sandbox_executions" -ge 7 ] \
      && [ "$test_reports" -ge 7 ] \
      && [ "$gates" -eq 17 ] \
      && [ "$manifest_valid" -eq 1 ] \
      && [ "$status" = "waiting_for_human" ] \
      && [ "$package_status" = "200" ] \
      && python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) >= 85 else 1)' "$hrs"; then
      api_get "/runs/$run_id/validation-manifest" | python3 -c 'import json,sys; row=json.load(sys.stdin); reports=row["test_reports"]; steps=row["steps"]; failed=any(item["status"]=="failed" for item in reports); assert not failed or max(item["iteration"] for item in steps if item["node_id"]=="Engineer") >= 2; assert row["generation_fingerprint"]; assert row["generated_files"]; assert all(item["model_call_id"] and item["step_execution_id"] for item in row["generated_files"]); assert all(item["model_call_id"] and item["step_execution_id"] for item in row["artifacts"])'
      api_get "/runs/$run_id/delivery-package" | python3 -c 'import json,sys; row=json.load(sys.stdin); assert row.get("path", "").startswith("s3://"); assert row.get("manifest_json", {}).get("storage_prefix", "").startswith("tenants/")'
      api_get "/runs/$run_id/delivery-package/download" | python3 -c 'import io,sys,zipfile; archive=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())); assert "manifest.json" in archive.namelist()'
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
  require_env ASF_ENCRYPTION_KEY
  export ASF_RUNTIME_PROFILE="production"
  export ASF_AGENT_PROVIDER="litellm"
  export ASF_WORKFLOW_BACKEND="temporal"
  export ASF_LITELLM_BASE_URL="${ASF_LITELLM_BASE_URL:-http://litellm:4000}"
  export ASF_DEFAULT_TENANT_ID="${ASF_FULL_TENANT_ID:-local-dev}"
  export ASF_DEFAULT_TENANT_NAME="${ASF_FULL_TENANT_NAME:-Local Development}"

  local service_host="localhost"
  if [ "${ASF_DOCKERIZED_CONTROL:-}" = "1" ]; then
    service_host="host.docker.internal"
    # Docker Desktop can advertise an unroutable IPv4 address before its
    # working IPv6 address to Python's urllib when the control container is on
    # the kind network. Prefer the discovered IPv6 literal for all host URLs.
    local docker_host_ipv6=""
    docker_host_ipv6="$(python3 - <<'PY'
import socket

for row in socket.getaddrinfo("host.docker.internal", 80, type=socket.SOCK_STREAM):
    if row[0] == socket.AF_INET6:
        print(row[4][0])
        break
PY
)"
    if [ -n "$docker_host_ipv6" ]; then
      service_host="[$docker_host_ipv6]"
    fi
  fi

  local api_origin="http://$service_host:8000"
  local web_origin="http://$service_host:3000"
  local temporal_origin="http://$service_host:8080"
  local keycloak_origin="http://$service_host:8081"
  local minio_origin="http://$service_host:9000"
  local litellm_origin="http://$service_host:4000"
  local prometheus_origin="http://$service_host:9090"
  local tempo_origin="http://$service_host:3200"
  local grafana_origin="http://$service_host:3001"
  if [ "${ASF_DOCKER_COMPOSE_NETWORK_CONNECTED:-}" = "1" ]; then
    api_origin="http://api:8000"
    web_origin="http://web:3000"
    temporal_origin="http://temporal-ui:8080"
    keycloak_origin="http://keycloak:8080"
    minio_origin="http://minio:9000"
    litellm_origin="http://litellm:4000"
    prometheus_origin="http://prometheus:9090"
    tempo_origin="http://tempo:3200"
    grafana_origin="http://grafana:3000"
  fi

  log "Validating Docker Compose configuration"
  (cd "$REPO_ROOT" && docker compose --profile full config >/dev/null)

  local cluster_name="${KIND_CLUSTER_NAME:-asf-local}"
  local context="kind-$cluster_name"
  local host_kubeconfig_path="${ASF_HOST_KUBECONFIG:-$REPO_ROOT/data/kube/asf-local-host.kubeconfig}"
  local control_kubeconfig_path="$host_kubeconfig_path"
  if kind get clusters | grep -qx "$cluster_name"; then
    mkdir -p "$(dirname "$host_kubeconfig_path")"
    if [ "${ASF_DOCKERIZED_CONTROL:-}" = "1" ]; then
      control_kubeconfig_path="${ASF_DOCKER_KUBECONFIG:-$REPO_ROOT/data/kube/asf-local-internal.kubeconfig}"
      kind get kubeconfig --internal --name "$cluster_name" > "$control_kubeconfig_path"
    else
      kind get kubeconfig --name "$cluster_name" > "$host_kubeconfig_path"
    fi
    chmod 0600 "$control_kubeconfig_path"
  fi

  export ASF_TEST_API_BASE_URL="${ASF_TEST_API_BASE_URL:-$api_origin}"
  export ASF_TEST_TENANT_ID="${ASF_TEST_TENANT_ID:-$ASF_DEFAULT_TENANT_ID}"
  local keycloak_user="${ASF_LOCAL_KEYCLOAK_USER:-operator@local.dev}"
  local keycloak_password="${ASF_LOCAL_KEYCLOAK_PASSWORD:-ChangeMe123!}"

  wait_for_http "API" "$ASF_TEST_API_BASE_URL/health"
  wait_for_http "Web" "$web_origin"
  wait_for_http "Temporal UI" "$temporal_origin"
  wait_for_http "Keycloak" "$keycloak_origin/realms/software-factory/.well-known/openid-configuration"
  wait_for_http "MinIO" "$minio_origin/minio/health/ready"
  wait_for_http "LiteLLM" "$litellm_origin/health/liveliness"
  wait_for_http "Prometheus" "$prometheus_origin/-/ready"
  wait_for_http "Tempo" "$tempo_origin/status/version"
  wait_for_http "Grafana" "$grafana_origin/api/health"
  validate_trace_pipeline

  log "Getting an OIDC service token for local API validation"
  token_json="$(
    curl -fsS -X POST "$keycloak_origin/realms/software-factory/protocol/openid-connect/token" \
      -H 'Host: localhost:8081' \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode 'client_id=software-factory-validation' \
      --data-urlencode "client_secret=${ASF_LOCAL_VALIDATION_CLIENT_SECRET:-local-validation-only-change-me}" \
      --data-urlencode 'grant_type=client_credentials'
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

  if [ -f "$control_kubeconfig_path" ]; then
    kubectl --kubeconfig "$control_kubeconfig_path" --context "$context" -n software-factory-sandbox get networkpolicy sandbox-deny-all >/dev/null
    kubectl --kubeconfig "$control_kubeconfig_path" --context "$context" -n software-factory-sandbox get pvc "${ASF_SANDBOX_WORKSPACE_PVC:-asf-sandbox-workspaces}" >/dev/null
  fi

  log "Running backend production-stack tests inside the API container"
  (cd "$REPO_ROOT" && docker compose --profile full exec -T \
    -e DATABASE_URL="sqlite:///:memory:" \
    -e ASF_DATABASE_URL="sqlite:///:memory:" \
    -e ASF_TEST_API_BASE_URL="http://api:8000" \
    -e ASF_TEST_BEARER_TOKEN="$ASF_TEST_BEARER_TOKEN" \
    -e ASF_TEST_TENANT_ID="$ASF_TEST_TENANT_ID" \
    -e ASF_TEST_POSTGRES_URL="postgresql+psycopg://factory_app:${ASF_POSTGRES_APP_PASSWORD:-factory_app}@postgres:5432/factory" \
    -e ASF_TEST_POSTGRES_ADMIN_URL="postgresql+psycopg://factory:factory@postgres:5432/factory" \
    api python -m pytest)

  if [ "${ASF_VALIDATE_ENTERPRISE_RUN:-1}" = "1" ]; then
    log "Starting ContractFlow through the real contracted AI-native journey"
    contract_json="$(ASF_VALIDATION_MISSION=contractflow ASF_VALIDATION_OUTPUT=json python3 "$REPO_ROOT/scripts/create-contracted-reference-run.py")"
    contract_run_id="$(printf '%s' "$contract_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')"
    contract_proposal_hash="$(printf '%s' "$contract_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["proposal_sha256"])')"
    log "ContractFlow run created: $contract_run_id"
    check_sse_once "$contract_run_id"
    wait_for_run_evidence "$contract_run_id"
    approved_json="$(api_post_json "/runs/$contract_run_id/approve" '{"comment":"Validação humana: escopo ContractFlow, evidências técnicas, rastreabilidade e package revisados e aceitos."}')"
    printf '%s' "$approved_json" | python3 -c 'import json,sys; row=json.load(sys.stdin); assert row.get("status") == "approved_for_homologation"; assert float(row.get("homologation_readiness_score") or 0) == 100'
    contract_fingerprint="$(api_get "/runs/$contract_run_id/validation-manifest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["generation_fingerprint"])')"

    log "Starting ServiceDesk through the real contracted AI-native journey"
    servicedesk_json="$(ASF_VALIDATION_MISSION=servicedesk ASF_VALIDATION_OUTPUT=json python3 "$REPO_ROOT/scripts/create-contracted-reference-run.py")"
    servicedesk_run_id="$(printf '%s' "$servicedesk_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')"
    servicedesk_proposal_hash="$(printf '%s' "$servicedesk_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["proposal_sha256"])')"
    log "ServiceDesk run created: $servicedesk_run_id"
    check_sse_once "$servicedesk_run_id"
    wait_for_run_evidence "$servicedesk_run_id"
    approved_json="$(api_post_json "/runs/$servicedesk_run_id/approve" '{"comment":"Validação humana: escopo ServiceDesk, evidências técnicas, rastreabilidade e package revisados e aceitos."}')"
    printf '%s' "$approved_json" | python3 -c 'import json,sys; row=json.load(sys.stdin); assert row.get("status") == "approved_for_homologation"; assert float(row.get("homologation_readiness_score") or 0) == 100'
    servicedesk_fingerprint="$(api_get "/runs/$servicedesk_run_id/validation-manifest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["generation_fingerprint"])')"

    python3 -c 'import sys; assert sys.argv[1] != sys.argv[2], "The two missions produced equivalent source fingerprints"; assert sys.argv[3] != sys.argv[4], "The two missions produced equivalent proposals"' "$contract_fingerprint" "$servicedesk_fingerprint" "$contract_proposal_hash" "$servicedesk_proposal_hash"
    export ASF_TEST_COMPLETED_RUN_ID="$servicedesk_run_id"
    export ASF_TEST_CONTRACTFLOW_RUN_ID="$contract_run_id"
    export ASF_TEST_SERVICEDESK_RUN_ID="$servicedesk_run_id"
    log "Validating the two mission manifests without skips"
    (cd "$REPO_ROOT" && docker compose --profile full exec -T \
      -e DATABASE_URL="sqlite:///:memory:" \
      -e ASF_DATABASE_URL="sqlite:///:memory:" \
      -e ASF_TEST_API_BASE_URL="http://api:8000" \
      -e ASF_TEST_BEARER_TOKEN="$ASF_TEST_BEARER_TOKEN" \
      -e ASF_TEST_TENANT_ID="$ASF_TEST_TENANT_ID" \
      -e ASF_TEST_CONTRACTFLOW_RUN_ID="$contract_run_id" \
      -e ASF_TEST_SERVICEDESK_RUN_ID="$servicedesk_run_id" \
      api python -m pytest -q tests/test_production_stack_contract.py -k two_ai_native_missions)
  fi

  log "Building frontend through Docker Compose"
  (cd "$REPO_ROOT" && docker compose --profile full build web)

  if [ "${ASF_VALIDATE_PLAYWRIGHT:-1}" = "1" ]; then
    log "Running Playwright in Docker against the Compose network"
    (cd "$REPO_ROOT" && docker compose --profile full --profile test build web-test web-e2e)
    (cd "$REPO_ROOT" && docker compose --profile full --profile test run --rm \
      -e ASF_TEST_TENANT_ID="$ASF_TEST_TENANT_ID" \
      -e ASF_TEST_COMPLETED_RUN_ID="${ASF_TEST_COMPLETED_RUN_ID:-}" \
      -e ASF_TEST_OIDC_USER="$keycloak_user" \
      -e ASF_TEST_OIDC_PASSWORD="$keycloak_password" \
      web-e2e)
    (cd "$REPO_ROOT" && docker compose --profile full --profile test stop web-test >/dev/null 2>&1 || true)
  fi

  log "Ensuring the Temporal worker remains active after test-profile orchestration"
  (cd "$REPO_ROOT" && docker compose --profile full up -d temporal-worker)
  (cd "$REPO_ROOT" && docker compose --profile full ps --status running --services | grep -qx 'temporal-worker') \
    || die "Temporal worker is not running after validation"

  log "Full-infra validation completed"
}

main "$@"
