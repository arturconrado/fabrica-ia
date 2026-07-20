#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ok() {
  printf '[asf-docker-doctor] OK: %s\n' "$*"
}

warn() {
  printf '[asf-docker-doctor] WARN: %s\n' "$*"
}

fail() {
  printf '[asf-docker-doctor] FAIL: %s\n' "$*"
  return 1
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

main() {
  local failures=0
  cd "$REPO_ROOT"
  load_env_file "$REPO_ROOT/.env"

  if command -v docker >/dev/null 2>&1; then
    ok "docker CLI found: $(docker --version)"
  else
    fail "docker CLI not found" || failures=$((failures + 1))
  fi

  if docker info >/dev/null 2>&1; then
    ok "Docker daemon is reachable"
  else
    fail "Docker daemon is not reachable. Start Docker Desktop and wait until it is ready." || failures=$((failures + 1))
  fi

  if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose found: $(docker compose version)"
  else
    fail "docker compose is not available" || failures=$((failures + 1))
  fi

  local docker_host="${DOCKER_HOST:-}"
  local socket_path="${docker_host#unix://}"
  if [ "$socket_path" = "$docker_host" ] || [ -z "$docker_host" ]; then
    socket_path="/var/run/docker.sock"
  fi
  if [ -S "$socket_path" ] || [ -L "$socket_path" ]; then
    ok "Docker socket exists at $socket_path"
  else
    warn "Docker socket not found at $socket_path; Docker Desktop may expose it through the active context"
  fi

  if [ -n "${OPENROUTER_API_KEY:-}" ] || [ -n "${OPENAI_API_KEY:-}" ]; then
    ok "Real LLM upstream key is configured"
  else
    fail "OPENROUTER_API_KEY or OPENAI_API_KEY is missing in environment/.env" || failures=$((failures + 1))
  fi

  if [ -n "${ASF_LITELLM_API_KEY:-}" ]; then
    ok "ASF_LITELLM_API_KEY is configured"
  else
    fail "ASF_LITELLM_API_KEY is missing in environment/.env" || failures=$((failures + 1))
  fi

  if [ -n "${ASF_ENCRYPTION_KEY:-}" ]; then
    ok "ASF_ENCRYPTION_KEY is configured"
  else
    fail "ASF_ENCRYPTION_KEY is missing in environment/.env" || failures=$((failures + 1))
  fi

  if "$REPO_ROOT/scripts/docker-control.sh" 'docker info >/dev/null && kind version >/dev/null && kubectl version --client=true >/dev/null && docker compose version >/dev/null'; then
    ok "Docker control container can reach Docker, kind, kubectl and Compose"
  else
    fail "Docker control container cannot operate the local Docker daemon" || failures=$((failures + 1))
  fi

  if [ "$failures" -gt 0 ]; then
    printf '[asf-docker-doctor] RESULT: %s blocking issue(s)\n' "$failures"
    exit 1
  fi

  ok "Docker-first local prerequisites are ready"
}

main "$@"
