#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export COMPOSE_FILE="$REPO_ROOT/docker-compose.yml:$REPO_ROOT/docker-compose.full.yml"

log() {
  printf '[asf-local-up] %s\n' "$*"
}

die() {
  printf '[asf-local-up] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    die "$name is required. Export a real value before starting the production-like local stack."
  fi
}

require_llm_upstream_env() {
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    die "OPENROUTER_API_KEY or OPENAI_API_KEY is required. Put the provider key only in the untracked .env file."
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

wait_for_pvc_bound() {
  local kubeconfig="$1"
  local context="$2"
  local namespace="$3"
  local pvc="$4"
  local deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    phase="$(kubectl --kubeconfig "$kubeconfig" --context "$context" -n "$namespace" get pvc "$pvc" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    if [ "$phase" = "Bound" ]; then
      return 0
    fi
    sleep 2
  done
  kubectl --kubeconfig "$kubeconfig" --context "$context" -n "$namespace" get pvc "$pvc" || true
  die "PVC $namespace/$pvc did not become Bound"
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local deadline=$((SECONDS + 240))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name is ready at $url"
      return 0
    fi
    sleep 3
  done
  die "$name did not become ready at $url"
}

main() {
  load_env_file "$REPO_ROOT/.env"

  require_cmd docker
  require_cmd kind
  require_cmd kubectl
  require_cmd curl
  require_cmd python3

  docker info >/dev/null 2>&1 || die "Docker is not running or not reachable"
  require_llm_upstream_env
  require_env ASF_LITELLM_API_KEY
  require_env ASF_ENCRYPTION_KEY

  local cluster_name="${KIND_CLUSTER_NAME:-asf-local}"
  local context="kind-$cluster_name"
  local kubeconfig_path="${ASF_DOCKER_KUBECONFIG:-$REPO_ROOT/data/kube/asf-local-internal.kubeconfig}"
  local host_kubeconfig_path="${ASF_HOST_KUBECONFIG:-$REPO_ROOT/data/kube/asf-local-host.kubeconfig}"
  local kind_config_path="$REPO_ROOT/data/kube/asf-local-kind.yaml"
  local sandbox_image="${ASF_SANDBOX_IMAGE:-asf-sandbox-runner:local}"
  local service_host="localhost"
  if [ "${ASF_DOCKERIZED_CONTROL:-}" = "1" ]; then
    service_host="host.docker.internal"
  fi

  export ASF_DOCKER_KUBECONFIG="$kubeconfig_path"
  export ASF_SANDBOX_WORKSPACE_PVC="${ASF_SANDBOX_WORKSPACE_PVC:-asf-sandbox-workspaces}"
  export ASF_SANDBOX_IMAGE="$sandbox_image"
  export ASF_AGENT_STEP_DELAY_MS="${ASF_AGENT_STEP_DELAY_MS:-900}"
  export ASF_RUNTIME_PROFILE="production"
  export ASF_AGENT_PROVIDER="litellm"
  export ASF_WORKFLOW_BACKEND="temporal"
  export ASF_LITELLM_BASE_URL="${ASF_LITELLM_BASE_URL:-http://litellm:4000}"
  export ASF_DEFAULT_TENANT_ID="${ASF_FULL_TENANT_ID:-local-dev}"
  export ASF_DEFAULT_TENANT_NAME="${ASF_FULL_TENANT_NAME:-Local Development}"
  export ASF_SANDBOX_RUNTIME_CLASS="${ASF_SANDBOX_RUNTIME_CLASS:-}"

  mkdir -p "$REPO_ROOT/data/api/workspaces" "$REPO_ROOT/data/kube"
  sed "s#__ASF_WORKSPACE_HOST_PATH__#$REPO_ROOT/data/api/workspaces#g" \
    "$REPO_ROOT/deploy/kind/asf-local.yaml" > "$kind_config_path"

  if ! kind get clusters | grep -qx "$cluster_name"; then
    log "Creating kind cluster $cluster_name"
    kind create cluster --name "$cluster_name" --config "$kind_config_path"
  else
    log "kind cluster $cluster_name already exists"
  fi

  # On the first Docker-first bootstrap the `kind` network is created after
  # this control container starts. Attach the running container explicitly so
  # the internal kubeconfig hostname is reachable without host networking.
  if [ "${ASF_DOCKERIZED_CONTROL:-}" = "1" ]; then
    docker network connect kind "${HOSTNAME}" >/dev/null 2>&1 || true
  fi

  log "Writing internal kubeconfig for Docker containers: $kubeconfig_path"
  kind get kubeconfig --internal --name "$cluster_name" > "$kubeconfig_path"
  chmod 0600 "$kubeconfig_path"
  log "Writing control kubeconfig: $host_kubeconfig_path"
  kind get kubeconfig --name "$cluster_name" > "$host_kubeconfig_path"
  chmod 0600 "$host_kubeconfig_path"

  local control_kubeconfig_path="$host_kubeconfig_path"
  if [ "${ASF_DOCKERIZED_CONTROL:-}" = "1" ]; then
    control_kubeconfig_path="$kubeconfig_path"
  fi

  log "Applying sandbox namespace, RBAC, NetworkPolicy and local PV/PVC"
  kubectl --kubeconfig "$control_kubeconfig_path" --context "$context" apply -f "$REPO_ROOT/deploy/k8s/namespace.yaml"
  kubectl --kubeconfig "$control_kubeconfig_path" --context "$context" apply -f "$REPO_ROOT/deploy/k8s/rbac.yaml"
  kubectl --kubeconfig "$control_kubeconfig_path" --context "$context" apply -f "$REPO_ROOT/deploy/k8s/sandbox-network-policy.yaml"
  kubectl --kubeconfig "$control_kubeconfig_path" --context "$context" apply -f "$REPO_ROOT/deploy/kind/sandbox-workspace-pv.yaml"
  wait_for_pvc_bound "$control_kubeconfig_path" "$context" "software-factory-sandbox" "$ASF_SANDBOX_WORKSPACE_PVC"

  log "Building and loading sandbox image into kind: $sandbox_image"
  docker build -t "$sandbox_image" "$REPO_ROOT/apps/sandbox-runner"
  kind load docker-image "$sandbox_image" --name "$cluster_name"

  log "Validating Docker Compose configuration"
  (cd "$REPO_ROOT" && docker compose --profile full config >/dev/null)

  log "Starting production-like local stack"
  (cd "$REPO_ROOT" && docker compose --profile full up --build -d)

  wait_for_http "API health" "http://$service_host:8000/health"
  wait_for_http "Web" "http://$service_host:3000"
  wait_for_http "Temporal UI" "http://$service_host:8080"
  wait_for_http "Keycloak" "http://$service_host:8081/realms/software-factory"
  log "Ensuring the local Keycloak realm accepts HTTP for Docker-first validation"
  (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master --user admin --password admin >/dev/null 2>&1)
  (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh update realms/software-factory -s sslRequired=NONE >/dev/null)
  local oidc_client_id
  oidc_client_id="$(cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh get clients -r software-factory \
    -q clientId=software-factory-web --fields id | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
  local oidc_mappers_json
  oidc_mappers_json="$(cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh get "clients/$oidc_client_id/protocol-mappers/models" -r software-factory)"
  if ! printf '%s' "$oidc_mappers_json" | python3 -c 'import json,sys; raise SystemExit(0 if any(row.get("name") == "software-factory-web-audience" for row in json.load(sys.stdin)) else 1)'; then
    printf '%s' '{"name":"software-factory-web-audience","protocol":"openid-connect","protocolMapper":"oidc-audience-mapper","config":{"included.client.audience":"software-factory-web","id.token.claim":"false","access.token.claim":"true","userinfo.token.claim":"false"}}' | \
      (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
        /opt/keycloak/bin/kcadm.sh create "clients/$oidc_client_id/protocol-mappers/models" -r software-factory -f - >/dev/null)
  fi
  (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh update "clients/$oidc_client_id" -r software-factory \
    -s standardFlowEnabled=true -s directAccessGrantsEnabled=false >/dev/null)
  local validation_client_id
  validation_client_id="$(cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh get clients -r software-factory \
    -q clientId=software-factory-validation --fields id | \
    python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0]["id"] if rows else "")')"
  if [ -z "$validation_client_id" ]; then
    printf '%s' '{"clientId":"software-factory-validation","name":"ASF Local Validation (test profile only)","enabled":true,"publicClient":false,"clientAuthenticatorType":"client-secret","secret":"local-validation-only-change-me","standardFlowEnabled":false,"directAccessGrantsEnabled":false,"serviceAccountsEnabled":true,"attributes":{"access.token.lifespan":"7200"},"protocolMappers":[{"name":"software-factory-web-audience","protocol":"openid-connect","protocolMapper":"oidc-audience-mapper","config":{"included.client.audience":"software-factory-web","id.token.claim":"false","access.token.claim":"true","userinfo.token.claim":"false"}}]}' | \
      (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
        /opt/keycloak/bin/kcadm.sh create clients -r software-factory -f - >/dev/null)
    validation_client_id="$(cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
      /opt/keycloak/bin/kcadm.sh get clients -r software-factory \
      -q clientId=software-factory-validation --fields id | \
      python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
  fi
  (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh update "clients/$validation_client_id" -r software-factory \
    -s enabled=true \
    -s publicClient=false \
    -s clientAuthenticatorType=client-secret \
    -s secret="${ASF_LOCAL_VALIDATION_CLIENT_SECRET:-local-validation-only-change-me}" \
    -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=true >/dev/null)
  (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh get "clients/$validation_client_id" -r software-factory) | \
    python3 -c 'import json,sys; row=json.load(sys.stdin); row.setdefault("attributes", {})["access.token.lifespan"]="7200"; json.dump(row, sys.stdout)' | \
    (cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
      /opt/keycloak/bin/kcadm.sh update "clients/$validation_client_id" -r software-factory -f - >/dev/null)
  wait_for_http "Keycloak OIDC discovery" "http://$service_host:8081/realms/software-factory/.well-known/openid-configuration"
  wait_for_http "MinIO" "http://$service_host:9000/minio/health/ready"
  wait_for_http "LiteLLM" "http://$service_host:4000/health/liveliness"
  wait_for_http "Prometheus" "http://$service_host:9090/-/ready"
  wait_for_http "Tempo" "http://$service_host:3200/status/version"
  wait_for_http "Grafana" "http://$service_host:3001/api/health"

  log "Bootstrapping the assisted-pilot tenant and OIDC owner idempotently"
  local keycloak_user="${ASF_LOCAL_KEYCLOAK_USER:-operator@local.dev}"
  owner_subject="$(cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh get users -r software-factory -q exact=true -q username="$keycloak_user" --fields id | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
  (cd "$REPO_ROOT" && docker compose --profile full exec -T \
    -e DATABASE_URL="postgresql+psycopg://factory:factory@postgres:5432/factory" \
    -e ASF_DATABASE_URL="postgresql+psycopg://factory:factory@postgres:5432/factory" \
    api \
    python -m app.cli.bootstrap_tenant \
    --tenant-id "$ASF_DEFAULT_TENANT_ID" \
    --tenant-name "$ASF_DEFAULT_TENANT_NAME" \
    --subject "$owner_subject" \
    --email "$keycloak_user" \
    --name "Local Operator" \
    --confirm "bootstrap assisted pilot tenant")
  local validation_subject
  validation_subject="$(cd "$REPO_ROOT" && docker compose --profile full exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh get "clients/$validation_client_id/service-account-user" -r software-factory --fields id | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  (cd "$REPO_ROOT" && docker compose --profile full exec -T \
    -e DATABASE_URL="postgresql+psycopg://factory:factory@postgres:5432/factory" \
    -e ASF_DATABASE_URL="postgresql+psycopg://factory:factory@postgres:5432/factory" \
    api \
    python -m app.cli.bootstrap_tenant \
    --tenant-id "$ASF_DEFAULT_TENANT_ID" \
    --tenant-name "$ASF_DEFAULT_TENANT_NAME" \
    --subject "$validation_subject" \
    --name "Local Validation Service" \
    --confirm "bootstrap assisted pilot tenant")

  log "Stack ready. Run: make docker-full-validate"
}

main "$@"
