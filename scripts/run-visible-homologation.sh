#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ASF_HOMOLOGATION_ENV_FILE:-$repo_root/.env.homologation.local}"

if [[ ! -f "$env_file" ]]; then
  echo "Homologation environment file not found: $env_file" >&2
  exit 1
fi

# Load only the browser-test identities and case reference. The file is not
# sourced, so its contents are never interpreted as shell commands.
while IFS='=' read -r env_key env_value; do
  case "$env_key" in
    ASF_TEST_SERVICE_ENGAGEMENT_ID|ASF_TEST_VP_OIDC_USER|ASF_TEST_VP_OIDC_PASSWORD|ASF_TEST_OIDC_USER|ASF_TEST_OIDC_PASSWORD)
      export "$env_key=$env_value"
      ;;
  esac
done < "$env_file"

export ASF_INTERACTIVE_HOMOLOGATION=1
export ASF_SIMULATE_VP="${ASF_SIMULATE_VP:-0}"
export ASF_PLAYWRIGHT_STEP_MODE="${ASF_PLAYWRIGHT_STEP_MODE:-1}"
export ASF_PLAYWRIGHT_SLOW_MO_MS="${ASF_PLAYWRIGHT_SLOW_MO_MS:-1800}"
export ASF_PLAYWRIGHT_AUTO_ADVANCE_MS="${ASF_PLAYWRIGHT_AUTO_ADVANCE_MS:-8000}"
export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-http://localhost:3000}"

cd "$repo_root/apps/web"
npm run test:e2e:homologation
