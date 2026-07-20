#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.vps.yml"

log() {
  printf '[asf-vps-up] %s\n' "$*"
}

die() {
  printf '[asf-vps-up] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    die "$name is required for VPS production Docker deployment"
  fi
}

require_urlsafe_password() {
  local name="$1"
  case "${!name}" in
    *[!a-zA-Z0-9._~-]*) die "$name must be URL-safe because it is embedded in a PostgreSQL DSN" ;;
  esac
}

require_llm_upstream_env() {
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    die "OPENROUTER_API_KEY or OPENAI_API_KEY is required for VPS production Docker deployment"
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
  local context="$1"
  local namespace="$2"
  local pvc="$3"
  local deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    phase="$(kubectl --context "$context" -n "$namespace" get pvc "$pvc" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    if [ "$phase" = "Bound" ]; then
      return 0
    fi
    sleep 2
  done
  require_urlsafe_password ASF_POSTGRES_PASSWORD
  require_urlsafe_password ASF_POSTGRES_APP_PASSWORD
  kubectl --context "$context" -n "$namespace" get pvc "$pvc" || true
  die "PVC $namespace/$pvc did not become Bound"
}

wait_for_container_health() {
  local service="$1"
  local deadline=$((SECONDS + 240))
  while [ "$SECONDS" -lt "$deadline" ]; do
    container_id="$(docker compose -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null || true)"
    if [ -n "$container_id" ]; then
      health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
      if [ "$health" = "healthy" ] || [ "$health" = "running" ]; then
        log "$service is $health"
        return 0
      fi
    fi
    sleep 3
  done
  docker compose -f "$COMPOSE_FILE" ps "$service" || true
  die "$service did not become healthy/running"
}

wait_for_public_health() {
  if [ "${ASF_SKIP_PUBLIC_HEALTH:-0}" = "1" ]; then
    log "Skipping public HTTPS health checks because ASF_SKIP_PUBLIC_HEALTH=1"
    return 0
  fi
  local url="https://$ASF_API_DOMAIN/health"
  local deadline=$((SECONDS + 300))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "Public API health is ready at $url"
      return 0
    fi
    sleep 5
  done
  die "Public API health did not become ready at $url. Check DNS, firewall ports 80/443 and Caddy logs."
}

render_keycloak_realm() {
  mkdir -p "$REPO_ROOT/data/keycloak-import"
  python3 - "$REPO_ROOT/deploy/keycloak/software-factory-realm.json" "$REPO_ROOT/data/keycloak-import/software-factory-realm.vps.json" "$ASF_PUBLIC_DOMAIN" "$ASF_DEFAULT_TENANT_ID" "$ASF_DEFAULT_TENANT_NAME" "$ASF_VPS_OPERATOR_SUBJECT" "$ASF_VPS_KEYCLOAK_USER" "$ASF_VPS_KEYCLOAK_PASSWORD" <<'PY'
import json
import sys

source, target, public_domain, tenant_id, tenant_name, subject, username, password = sys.argv[1:9]
with open(source, "r", encoding="utf-8") as handle:
    realm = json.load(handle)
for client in realm.get("clients", []):
    if client.get("clientId") == "software-factory-web":
        client["redirectUris"] = [f"https://{public_domain}/*"]
        client["webOrigins"] = [f"https://{public_domain}"]
realm["clients"] = [client for client in realm.get("clients", []) if client.get("clientId") != "software-factory-validation"]
operator = next(user for user in realm.get("users", []) if user.get("username") == "operator@local.dev")
operator["id"] = subject
operator["username"] = username
operator["email"] = username
operator["credentials"] = [{"type": "password", "value": password, "temporary": False}]
operator.setdefault("attributes", {})
operator["attributes"]["tenant_id"] = [tenant_id]
operator["attributes"]["tenant_name"] = [tenant_name]
realm["users"] = [operator]
with open(target, "w", encoding="utf-8") as handle:
    json.dump(realm, handle, indent=2)
PY
}

render_alertmanager_config() {
  mkdir -p "$REPO_ROOT/data/observability"
  python3 - "$REPO_ROOT/data/observability/alertmanager.yml" "$ASF_ALERT_WEBHOOK_URL" <<'PY'
import json
import sys

target, webhook_url = sys.argv[1:3]
with open(target, "w", encoding="utf-8") as handle:
    handle.write(
        "global:\n  resolve_timeout: 5m\n"
        "route:\n  receiver: asf-operations\n  group_wait: 30s\n  group_interval: 5m\n  repeat_interval: 4h\n"
        "receivers:\n  - name: asf-operations\n    webhook_configs:\n      - send_resolved: true\n"
        f"        url: {json.dumps(webhook_url)}\n"
    )
PY
  chmod 0600 "$REPO_ROOT/data/observability/alertmanager.yml"
}

main() {
  load_env_file "$REPO_ROOT/.env.vps"

  require_cmd docker
  require_cmd kind
  require_cmd kubectl
  require_cmd curl
  require_cmd python3

  docker info >/dev/null 2>&1 || die "Docker is not running or not reachable"

  require_llm_upstream_env
  for name in \
    ASF_PUBLIC_DOMAIN ASF_API_DOMAIN ASF_AUTH_DOMAIN ASF_MINIO_DOMAIN ASF_TLS_EMAIL \
    ASF_LITELLM_API_KEY ASF_POSTGRES_PASSWORD ASF_TEMPORAL_POSTGRES_PASSWORD \
    ASF_POSTGRES_APP_PASSWORD ASF_KEYCLOAK_DB_PASSWORD KEYCLOAK_ADMIN_PASSWORD \
    ASF_MINIO_ROOT_USER ASF_MINIO_ROOT_PASSWORD ASF_VPS_OPERATOR_SUBJECT \
    ASF_VPS_KEYCLOAK_USER ASF_VPS_KEYCLOAK_PASSWORD ASF_BACKUP_REMOTE_ENDPOINT \
    ASF_BACKUP_REMOTE_ACCESS_KEY ASF_BACKUP_REMOTE_SECRET_KEY ASF_BACKUP_REMOTE_BUCKET \
    ASF_ALERT_WEBHOOK_URL; do
    require_env "$name"
  done
  case "$ASF_BACKUP_REMOTE_ENDPOINT" in
    *localhost*|*127.0.0.1*|*minio:9000*|*"$ASF_MINIO_DOMAIN"*)
      die "ASF_BACKUP_REMOTE_ENDPOINT must be outside this VPS/MinIO deployment"
      ;;
  esac

  export ASF_DEFAULT_TENANT_ID="${ASF_DEFAULT_TENANT_ID:-production}"
  export ASF_DEFAULT_TENANT_NAME="${ASF_DEFAULT_TENANT_NAME:-Production}"
  local cluster_name="${KIND_CLUSTER_NAME:-asf-vps}"
  local context="kind-$cluster_name"
  local kubeconfig_path="${ASF_DOCKER_KUBECONFIG:-$REPO_ROOT/data/kube/asf-vps-internal.kubeconfig}"
  local kind_config_path="$REPO_ROOT/data/kube/asf-vps-kind.yaml"
  local sandbox_image="${ASF_SANDBOX_IMAGE:-asf-sandbox-runner:local}"

  export ASF_DOCKER_KUBECONFIG="$kubeconfig_path"
  export ASF_SANDBOX_WORKSPACE_PVC="${ASF_SANDBOX_WORKSPACE_PVC:-asf-sandbox-workspaces}"
  export ASF_SANDBOX_IMAGE="$sandbox_image"
  export ASF_SANDBOX_RUNTIME_CLASS="${ASF_SANDBOX_RUNTIME_CLASS:-}"

  mkdir -p "$REPO_ROOT/data/api/workspaces" "$REPO_ROOT/data/kube"
  sed "s#__ASF_WORKSPACE_HOST_PATH__#$REPO_ROOT/data/api/workspaces#g" \
    "$REPO_ROOT/deploy/kind/asf-local.yaml" > "$kind_config_path"
  render_keycloak_realm
  render_alertmanager_config

  if ! kind get clusters | grep -qx "$cluster_name"; then
    log "Creating kind cluster $cluster_name"
    kind create cluster --name "$cluster_name" --config "$kind_config_path"
  else
    log "kind cluster $cluster_name already exists"
  fi

  log "Writing internal kubeconfig for Docker containers: $kubeconfig_path"
  kind get kubeconfig --internal --name "$cluster_name" > "$kubeconfig_path"
  chmod 0600 "$kubeconfig_path"

  log "Applying sandbox namespace, RBAC, NetworkPolicy and local PV/PVC"
  kubectl --context "$context" apply -f "$REPO_ROOT/deploy/k8s/namespace.yaml"
  kubectl --context "$context" apply -f "$REPO_ROOT/deploy/k8s/rbac.yaml"
  kubectl --context "$context" apply -f "$REPO_ROOT/deploy/k8s/sandbox-network-policy.yaml"
  kubectl --context "$context" apply -f "$REPO_ROOT/deploy/kind/sandbox-workspace-pv.yaml"
  wait_for_pvc_bound "$context" "software-factory-sandbox" "$ASF_SANDBOX_WORKSPACE_PVC"

  log "Building and loading sandbox image into kind: $sandbox_image"
  docker build -t "$sandbox_image" "$REPO_ROOT/apps/sandbox-runner"
  kind load docker-image "$sandbox_image" --name "$cluster_name"

  log "Validating VPS Docker Compose configuration"
  docker compose -f "$COMPOSE_FILE" config >/dev/null

  log "Starting VPS production Docker stack"
  docker compose -f "$COMPOSE_FILE" up --build -d

  wait_for_container_health postgres
  wait_for_container_health temporal-postgres
  wait_for_container_health keycloak-postgres
  wait_for_container_health api
  wait_for_container_health backup-offsite
  wait_for_container_health alertmanager
  log "Bootstrapping the first tenant and owner with the configured OIDC subject"
  docker compose -f "$COMPOSE_FILE" exec -T api \
    -e DATABASE_URL="postgresql+psycopg://factory:$ASF_POSTGRES_PASSWORD@postgres:5432/factory" \
    -e ASF_DATABASE_URL="postgresql+psycopg://factory:$ASF_POSTGRES_PASSWORD@postgres:5432/factory" \
    python -m app.cli.bootstrap_tenant \
    --tenant-id "$ASF_DEFAULT_TENANT_ID" \
    --tenant-name "$ASF_DEFAULT_TENANT_NAME" \
    --subject "$ASF_VPS_OPERATOR_SUBJECT" \
    --email "$ASF_VPS_KEYCLOAK_USER" \
    --name "Initial Owner" \
    --confirm "bootstrap assisted pilot tenant"
  wait_for_public_health

  log "VPS Docker stack is ready. Run: make vps-docker-validate"
}

main "$@"
