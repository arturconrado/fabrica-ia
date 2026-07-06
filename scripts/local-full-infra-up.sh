#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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
    die "OPENROUTER_API_KEY or OPENAI_API_KEY is required. Put your real OpenRouter key in .env as OPENROUTER_API_KEY=sk-or-v1-..."
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
  kubectl --context "$context" -n "$namespace" get pvc "$pvc" || true
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

  docker info >/dev/null 2>&1 || die "Docker is not running or not reachable"
  require_llm_upstream_env
  require_env ASF_LITELLM_API_KEY

  local cluster_name="${KIND_CLUSTER_NAME:-asf-local}"
  local context="kind-$cluster_name"
  local kubeconfig_path="${ASF_DOCKER_KUBECONFIG:-$REPO_ROOT/data/kube/asf-local-internal.kubeconfig}"
  local kind_config_path="$REPO_ROOT/data/kube/asf-local-kind.yaml"
  local sandbox_image="${ASF_SANDBOX_IMAGE:-asf-sandbox-runner:local}"

  export ASF_DOCKER_KUBECONFIG="$kubeconfig_path"
  export ASF_SANDBOX_WORKSPACE_PVC="${ASF_SANDBOX_WORKSPACE_PVC:-asf-sandbox-workspaces}"
  export ASF_SANDBOX_IMAGE="$sandbox_image"
  export ASF_AGENT_STEP_DELAY_MS="${ASF_AGENT_STEP_DELAY_MS:-900}"
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

  log "Validating Docker Compose configuration"
  (cd "$REPO_ROOT" && docker compose config >/dev/null)

  log "Starting production-like local stack"
  (cd "$REPO_ROOT" && docker compose up --build -d)

  wait_for_http "API health" "http://localhost:8000/health"
  wait_for_http "Web" "http://localhost:3000"
  wait_for_http "Temporal UI" "http://localhost:8080"
  wait_for_http "Keycloak" "http://localhost:8081/realms/software-factory/.well-known/openid-configuration"
  wait_for_http "MinIO" "http://localhost:9000/minio/health/ready"
  wait_for_http "LiteLLM" "http://localhost:4000/health/liveliness"

  log "Stack ready. Run: make local-full-validate"
}

main "$@"
