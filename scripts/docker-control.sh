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

for name in \
  OPENROUTER_API_KEY \
  OPENAI_API_KEY \
  ASF_LITELLM_API_KEY \
  ASF_AGENT_STEP_DELAY_MS \
  ASF_SANDBOX_RUNTIME_CLASS \
  ASF_VALIDATE_ENTERPRISE_RUN \
  ASF_VALIDATE_PLAYWRIGHT \
  ASF_VALIDATE_RUN_TIMEOUT_SECONDS \
  ASF_DELETE_KIND \
  KIND_CLUSTER_NAME; do
  if [ -n "${!name:-}" ]; then
    run_args+=("-e" "$name")
  fi
done

log "Running inside Docker control container"
docker run "${run_args[@]}" "$IMAGE" "$*"
