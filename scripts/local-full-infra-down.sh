#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export COMPOSE_FILE="$REPO_ROOT/docker-compose.yml:$REPO_ROOT/docker-compose.full.yml"

log() {
  printf '[asf-local-down] %s\n' "$*"
}

main() {
  cd "$REPO_ROOT"
  log "Stopping Docker Compose stack"
  docker compose down --remove-orphans

  if [ "${ASF_DELETE_KIND:-0}" = "1" ]; then
    local cluster_name="${KIND_CLUSTER_NAME:-asf-local}"
    if command -v kind >/dev/null 2>&1 && kind get clusters | grep -qx "$cluster_name"; then
      log "Deleting kind cluster $cluster_name"
      kind delete cluster --name "$cluster_name"
    fi
  else
    log "Keeping kind cluster. Set ASF_DELETE_KIND=1 to delete it."
  fi
}

main "$@"
