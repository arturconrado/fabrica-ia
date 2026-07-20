#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '[asf-docker-control] %s\n' "$*"
}

die() {
  printf '[asf-docker-control] ERROR: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || die "Docker is required"
docker info >/dev/null 2>&1 || die "Docker is not running or not reachable"

IMAGE="${ASF_LOCAL_CONTROL_IMAGE:-asf-local-control:latest}"
DOCKERFILE="$REPO_ROOT/deploy/docker/local-control.Dockerfile"

if [ "$#" -eq 0 ]; then
  set -- "bash"
fi

log "Building control image $IMAGE"
docker build -f "$DOCKERFILE" -t "$IMAGE" "$REPO_ROOT"

run_args=(--rm)
if [ -t 0 ]; then
  run_args+=(-it)
fi

run_args+=(
  -v /var/run/docker.sock:/var/run/docker.sock
  -v "$REPO_ROOT:$REPO_ROOT"
  -w "$REPO_ROOT"
  -e DOCKER_HOST=unix:///var/run/docker.sock
  -e ASF_DOCKERIZED_CONTROL=1
)

# Docker Desktop already publishes a routable host.docker.internal address. An
# explicit host-gateway entry on macOS shadows that address with an unroutable
# IPv4 address for Python clients attached to the kind network. Native Linux
# engines still need the explicit mapping.
if [ "$(uname -s)" = "Linux" ]; then
  run_args+=(--add-host host.docker.internal:host-gateway)
fi

# When the kind network already exists, place the control container on it so
# the internal kubeconfig can resolve the control-plane container directly.
if docker network inspect kind >/dev/null 2>&1; then
  run_args+=(--network kind)
fi

# Join the running Compose network as well. This gives validation traffic a
# direct service-to-service path (api:8000) while retaining access to the kind
# control plane for sandbox checks.
compose_project="$(basename "$REPO_ROOT" | tr '[:upper:]' '[:lower:]')"
compose_network="$(
  docker network ls \
    --filter "label=com.docker.compose.project=$compose_project" \
    --filter "label=com.docker.compose.network=default" \
    --format '{{.Name}}' | head -n 1
)"
if [ -n "$compose_network" ]; then
  run_args+=(--network "$compose_network" -e ASF_DOCKER_COMPOSE_NETWORK_CONNECTED=1)
fi

for name in \
  OPENROUTER_API_KEY \
  OPENAI_API_KEY \
  ASF_LITELLM_API_KEY \
  ASF_ENCRYPTION_KEY \
  ASF_AGENT_STEP_DELAY_MS \
  ASF_SANDBOX_RUNTIME_CLASS \
  ASF_VALIDATE_ENTERPRISE_RUN \
  ASF_VALIDATE_PLAYWRIGHT \
  ASF_VALIDATE_RUN_TIMEOUT_SECONDS \
  ASF_VALIDATION_ID \
  ASF_TEST_COMPLETED_RUN_ID \
  ASF_DELETE_KIND \
  KIND_CLUSTER_NAME; do
  if [ -n "${!name:-}" ]; then
    run_args+=("-e" "$name")
  fi
done

log "Running inside Docker control container"
docker run "${run_args[@]}" "$IMAGE" "$@"
