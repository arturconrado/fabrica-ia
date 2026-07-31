#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
phase="${1:-check}"
run_id="${ASF_PRODUCTION_E2E_RUN_ID:-production-candidate}"
export ASF_PRODUCTION_E2E_RUN_ID="$run_id"
portfolio_version="${ASF_PORTFOLIO_VERSION:-2.1}"
export ASF_PORTFOLIO_VERSION="$portfolio_version"
export ASF_EVIDENCE_RUNTIME_PROFILE="homologation"
export ASF_AGENT_PROVIDER="${ASF_AGENT_PROVIDER:-litellm}"
export ASF_WORKFLOW_BACKEND="${ASF_WORKFLOW_BACKEND:-temporal}"
evidence_root="${ASF_PRODUCTION_E2E_OUTPUT_DIR:-$repo_root/artifacts/production-readiness/$run_id}"
load_dir="$evidence_root/load"
playwright_report="$evidence_root/playwright.json"
state_dir="$evidence_root/state"

log() { printf '[asf-production-e2e] %s\n' "$*"; }
die() { printf '[asf-production-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
require_env() { local name="$1"; [ -n "${!name:-}" ] || die "$name is required"; }
require_confirmation() {
  local name="$1" expected="$2" reason="$3"
  [ "${!name:-}" = "$expected" ] || die "$reason; set $name=$expected"
}
marker() { printf '%s/%s.passed.json' "$state_dir" "$1"; }
require_phase() { [ -f "$(marker "$1")" ] || die "Phase '$1' has not passed for run '$run_id'"; }
mark_phase() {
  local completed="$1" log_path="${2:-}"
  PHASE_NAME="$completed" LOG_PATH="$log_path" RUN_ID="$run_id" python3 - "$state_dir" <<'PY'
import hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
log_path = pathlib.Path(os.environ["LOG_PATH"]) if os.environ.get("LOG_PATH") else None
digest = hashlib.sha256(log_path.read_bytes()).hexdigest() if log_path and log_path.exists() else None
payload = {"schema_version": "production-e2e-phase-v1", "run_id": os.environ["RUN_ID"],
           "phase": os.environ["PHASE_NAME"], "log_sha256": digest}
(root / f'{os.environ["PHASE_NAME"]}.passed.json').write_text(json.dumps(payload, sort_keys=True) + "\n")
PY
}

run_final_check() {
  local base_url="${ASF_RELEASE_API_BASE_URL:-http://127.0.0.1:8000}"
  local target="${1:-${ASF_PRODUCTION_E2E_TARGET:-market_ready}}"
  python3 "$repo_root/scripts/build-production-evidence-manifest.py" \
    --evidence-root "$evidence_root" --repo-root "$repo_root" >/dev/null
  local gate_status=0
  if [ "${ASF_PRODUCTION_E2E_ALLOW_REMOTE:-0}" = "1" ]; then
    python3 "$repo_root/scripts/production-readiness-gate.py" \
      --base-url "$base_url" --load-dir "$load_dir" \
      --playwright-report "$playwright_report" --output-dir "$evidence_root" \
      --backup-restore-report "$evidence_root/backup-restore/backup-restore.json" \
      --agentic-journey-report "$evidence_root/agentic-journey-evaluation.json" \
      --commercial-ai-case-report "$evidence_root/commercial-ai-case-evaluation.json" \
      --workflow-candidate-report "$evidence_root/workflow-candidate-evaluation.json" \
      --manifest "$evidence_root/manifest.json" \
      --run-id "$run_id" \
      --target "$target" \
      --portfolio-version "$portfolio_version" \
      --cost-cap-usd "${ASF_PRODUCTION_E2E_COST_CAP_USD:-50}" \
      --allow-remote || gate_status=$?
  else
    python3 "$repo_root/scripts/production-readiness-gate.py" \
      --base-url "$base_url" --load-dir "$load_dir" \
      --playwright-report "$playwright_report" --output-dir "$evidence_root" \
      --backup-restore-report "$evidence_root/backup-restore/backup-restore.json" \
      --agentic-journey-report "$evidence_root/agentic-journey-evaluation.json" \
      --commercial-ai-case-report "$evidence_root/commercial-ai-case-evaluation.json" \
      --workflow-candidate-report "$evidence_root/workflow-candidate-evaluation.json" \
      --manifest "$evidence_root/manifest.json" \
      --run-id "$run_id" \
      --target "$target" \
      --portfolio-version "$portfolio_version" \
      --cost-cap-usd "${ASF_PRODUCTION_E2E_COST_CAP_USD:-50}" || gate_status=$?
  fi
  python3 "$repo_root/scripts/build-production-evidence-manifest.py" \
    --evidence-root "$evidence_root" --repo-root "$repo_root" >/dev/null
  return "$gate_status"
}

run_preflight() {
  require_confirmation ASF_PRODUCTION_E2E_CONFIRM RUN_AUTHORIZED_PRODUCTION_E2E \
    "Paid provider execution and sustained local load need explicit authorization"
  [ "${ASF_PROVIDER_CREDENTIAL_ROTATED:-}" = "1" ] \
    || die "Attest the rotated provider credential with ASF_PROVIDER_CREDENTIAL_ROTATED=1"
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    die "OPENROUTER_API_KEY or OPENAI_API_KEY must be supplied only through the environment"
  fi
  python3 "$repo_root/scripts/provider_credential_preflight.py" \
    || die "Provider credential preflight failed without printing the credential"
  local cap="${ASF_PRODUCTION_E2E_COST_CAP_USD:-50}"
  python3 - "$cap" <<'PY'
import sys
cap = float(sys.argv[1])
if not 0 < cap <= 50:
    raise SystemExit("ASF_PRODUCTION_E2E_COST_CAP_USD must be > 0 and <= 50")
PY
  log "Projecting Portfolio $portfolio_version / workflow 2.14.0 token usage before paid calls"
  (cd "$repo_root/apps/api" && uv run python ../../scripts/simulate_portfolio_token_costs.py \
    --json-output "$evidence_root/token-cost-simulation.json" \
    --markdown-output "$evidence_root/token-cost-simulation.md")
  for name in ASF_RELEASE_BEARER_TOKEN ASF_RELEASE_TENANT_ID \
    ASF_RELEASE_OPERATOR \
    ASF_TEST_SERVICE_ENGAGEMENT_ID \
    ASF_TEST_OIDC_USER ASF_TEST_OIDC_PASSWORD ASF_TEST_VP_OIDC_USER ASF_TEST_VP_OIDC_PASSWORD \
    ASF_LOAD_TENANT_ID ASF_LOAD_VP_TENANT_ID; do
    require_env "$name"
  done
  case "$ASF_RELEASE_TENANT_ID" in
    release-*|homologation-*) ;;
    *) die "ASF_RELEASE_TENANT_ID must identify a dedicated release/homologation tenant" ;;
  esac
  [ "$ASF_LOAD_TENANT_ID" = "$ASF_RELEASE_TENANT_ID" ] \
    || die "Owner load identity must be scoped to ASF_RELEASE_TENANT_ID"
  [ "$ASF_LOAD_VP_TENANT_ID" = "$ASF_RELEASE_TENANT_ID" ] \
    || die "VP load identity must be scoped to ASF_RELEASE_TENANT_ID"
  if [ "${ASF_PRODUCTION_E2E_ALLOW_REMOTE:-0}" = "1" ]; then
    for name in ASF_LOAD_BEARER_TOKEN ASF_LOAD_VP_BEARER_TOKEN; do require_env "$name"; done
  fi
  mkdir -p "$evidence_root" "$state_dir"
  PREFLIGHT_ORIGIN="${ASF_RELEASE_API_BASE_URL:-http://127.0.0.1:8000}" \
    PREFLIGHT_CAP="$cap" PREFLIGHT_RUN_ID="$run_id" python3 - "$evidence_root/preflight.json" <<'PY'
import hashlib, json, os, pathlib, sys
payload = {"schema_version": "production-e2e-preflight-v1", "run_id": os.environ["PREFLIGHT_RUN_ID"],
           "target_origin": os.environ["PREFLIGHT_ORIGIN"], "cost_cap_usd": float(os.environ["PREFLIGHT_CAP"]),
           "provider_credential_rotated": True, "secrets_persisted": False,
           "identity_fingerprints": {
             role: hashlib.sha256(os.environ[key].encode()).hexdigest()
             for role, key in (("owner", "ASF_TEST_OIDC_USER"), ("vp", "ASF_TEST_VP_OIDC_USER"))}}
if payload["identity_fingerprints"]["owner"] == payload["identity_fingerprints"]["vp"]:
    raise SystemExit("owner and VP identities must be distinct")
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
  mark_phase preflight "$evidence_root/preflight.json"
  python3 "$repo_root/scripts/build-production-evidence-manifest.py" \
    --evidence-root "$evidence_root" --repo-root "$repo_root" >/dev/null
  log "Preflight passed without printing or persisting credentials"
}

run_local() {
  require_phase preflight
  export ASF_HOMOLOGATION_GLOBAL_BUDGET_USD="${ASF_PRODUCTION_E2E_COST_CAP_USD:-50}"
  require_confirmation ASF_PRODUCTION_E2E_FAULT_CONFIRM RUN_ISOLATED_FAULT_INJECTION \
    "The homologation-only fault provider needs explicit authorization"
  mkdir -p "$evidence_root"
  log "Validating the eight realistic agentic journey contracts"
  (cd "$repo_root/apps/api" && uv run python ../../scripts/evaluate-agentic-journeys.py validate \
    --portfolio-version "$portfolio_version") \
    2>&1 | tee "$evidence_root/agentic-journey-scenarios.log"
  log "Validating the canonical AI-native commercial case and held-out dataset"
  (cd "$repo_root/apps/api" && uv run python ../../scripts/evaluate-commercial-ai-case.py validate \
    --portfolio-version "$portfolio_version") \
    2>&1 | tee "$evidence_root/commercial-ai-case.log"
  log "Validating independent Discovery and code-delivering AI MVP operation modes"
  (cd "$repo_root/apps/api" && uv run python ../../scripts/validate-commercial-operation-matrix.py) \
    2>&1 | tee "$evidence_root/commercial-operation-matrix.log"
  log "Validating production-like infrastructure and real-provider execution"
  ASF_VALIDATE_PLAYWRIGHT=0 ASF_VALIDATION_RUN_ID_OUTPUT="$evidence_root/technical-runs.env" \
    "$repo_root/scripts/local-full-infra-validate.sh" 2>&1 | tee "$evidence_root/local.log"
  log "Running three isolated restore attempts, RPO/ledger checks and corrupt-backup detection"
  mkdir -p "$evidence_root/backup-restore"
  "$repo_root/scripts/local-backup-restore-drill.sh" "$evidence_root/backup-restore" \
    2>&1 | tee "$evidence_root/backup-restore/restore-log.txt"
  log "Validating deterministic fault provider and bounded gateway behavior"
  (cd "$repo_root" && docker compose -f docker-compose.yml -f docker-compose.homologation.yml \
    --profile fault-injection up -d --wait --wait-timeout 60 fault-provider)
  (cd "$repo_root" && docker compose -f docker-compose.yml -f docker-compose.homologation.yml \
    --profile fault-injection exec -T api python -c '
import json, socket, urllib.error, urllib.request
origin = "http://fault-provider:8000"
payload = json.dumps({"model":"asf-fast","messages":[{"role":"user","content":"homologation"}]}).encode()
def status(mode, timeout=2):
    request = urllib.request.Request(f"{origin}/{mode}/v1/chat/completions", data=payload,
        headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
assert status("rate_limit")[0] == 429
assert status("unavailable")[0] == 503
assert status("schema_invalid")[0] == 200
assert status("truncated")[1].endswith(b"[")
try:
    status("timeout", 0.1)
    raise AssertionError("timeout mode returned before client deadline")
except (TimeoutError, socket.timeout, urllib.error.URLError):
    pass
try:
    status("connection_interrupted")
    raise AssertionError("interrupted mode returned a complete body")
except Exception as exc:
    assert type(exc).__name__ in {"IncompleteRead", "RemoteDisconnected", "URLError"}
')
  (cd "$repo_root/apps/api" && uv run pytest -q \
    tests/test_fault_provider.py tests/test_model_gateway_routing.py) 2>&1 | tee "$evidence_root/fault-provider-tests.log"
  mark_phase local "$evidence_root/local.log"
}

run_human() {
  require_phase local
  [ "${ASF_SIMULATE_VP:-0}" = "0" ] || die "Human phase forbids ASF_SIMULATE_VP=1"
  local technical_runs="$evidence_root/technical-runs.env"
  [ -f "$technical_runs" ] || die "Technical mission ids were not produced by the local phase"
  while IFS='=' read -r env_key env_value; do
    case "$env_key" in
      ASF_TEST_CONTRACTFLOW_RUN_ID|ASF_TEST_SERVICEDESK_RUN_ID) export "$env_key=$env_value" ;;
    esac
  done < "$technical_runs"
  require_env ASF_TEST_CONTRACTFLOW_RUN_ID
  require_env ASF_TEST_SERVICEDESK_RUN_ID
  log "Starting owner/VP visible journey. Both decisions must be made by their real identities."
  ASF_SIMULATE_VP=0 ASF_HOMOLOGATION_REPORT="$evidence_root/human-playwright.json" \
    "$repo_root/scripts/run-visible-homologation.sh" 2>&1 | tee "$evidence_root/human.log"
  export ASF_TEST_COMPLETED_RUN_ID="$ASF_TEST_SERVICEDESK_RUN_ID"
  log "Running strict release browser suite after the real human decisions"
  local playwright_status=0
  (cd "$repo_root/apps/web" && PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-http://127.0.0.1:3000}" \
    ASF_PLAYWRIGHT_RELEASE_REPORT="$playwright_report" npm run test:e2e:release) \
    2>&1 | tee "$evidence_root/playwright.log" || playwright_status=$?
  python3 "$repo_root/scripts/finalize-playwright-evidence.py" \
    --report "$playwright_report" --repo-root "$repo_root" --exit-code "$playwright_status"
  [ "$playwright_status" -eq 0 ] || die "Playwright release suite failed"
  mark_phase human "$evidence_root/human.log"
}

run_load() {
  require_phase human
  mkdir -p "$load_dir"
  if [ "${ASF_PRODUCTION_E2E_ALLOW_REMOTE:-0}" = "1" ]; then
    require_confirmation ASF_PRODUCTION_E2E_REMOTE_CONFIRM RUN_AUTHORIZED_REMOTE_LOAD \
      "Remote load needs independent authorization"
    for profile in baseline-2 load-20 load-50 stress-200 spike-500 soak-20; do
      log "Running full-duration remote owner/VP profile $profile; stop-on-first-failure is active"
      python3 "$repo_root/scripts/portfolio-load-test.py" --profile "$profile" \
        --base-url "${ASF_RELEASE_API_BASE_URL:-http://127.0.0.1:8000}" \
        --output-dir "$load_dir" --portfolio-version "$portfolio_version" --allow-remote
    done
  else
    log "Running local profiles with renewable owner/VP PKCE sessions; stop-on-first-failure is active"
    (
      cd "$repo_root/apps/web"
      ASF_PRODUCTION_E2E_LOAD_DIR="$load_dir" \
        node scripts/run-local-portfolio-load.mjs
    )
  fi
  mark_phase load "$load_dir/portfolio-v2-soak-20.json"
}

run_rotate_credential() {
  require_phase load
  "$repo_root/scripts/rotate-release-service-account-secret.sh" \
    "$evidence_root/credential-rotation.json"
  mark_phase credential-rotation "$evidence_root/credential-rotation.json"
}

run_agentic_journey_evaluation() {
  local evidence_path="${ASF_AGENTIC_JOURNEY_EVIDENCE:-$evidence_root/agentic-journey-evidence.json}"
  local report_path="$evidence_root/agentic-journey-evaluation.json"
  [ -f "$evidence_path" ] \
    || die "Repeated provider-real evidence for all eight journeys is missing: $evidence_path"
  log "Evaluating three or more real runs for every contracted Portfolio $portfolio_version journey"
  (cd "$repo_root/apps/api" && uv run python ../../scripts/evaluate-agentic-journeys.py evaluate \
    --portfolio-version "$portfolio_version" \
    --evidence "$evidence_path" --output "$report_path")
}

run_workflow_candidate_evaluation() {
  local evidence_path="${ASF_WORKFLOW_CANDIDATE_EVIDENCE:-$evidence_root/workflow-candidate-evidence.json}"
  local report_path="$evidence_root/workflow-candidate-evaluation.json"
  [ -f "$evidence_path" ] \
    || die "Three provider-real repetitions for workflow 2.13.2 and 2.14.0 are missing: $evidence_path"
  log "Comparing workflow 2.14.0 with immutable 2.13.2 on the fixed dataset"
  (cd "$repo_root/apps/api" && uv run python ../../scripts/evaluate-workflow-candidate.py \
    --evidence "$evidence_path" --output "$report_path")
}

run_commercial_ai_case_evaluation() {
  local evidence_path="${ASF_COMMERCIAL_AI_CASE_EVIDENCE:-$evidence_root/commercial-ai-case-evidence.json}"
  local report_path="$evidence_root/commercial-ai-case-evaluation.json"
  [ -f "$evidence_path" ] \
    || die "Provider-real evidence for the canonical commercial AI case is missing: $evidence_path"
  log "Evaluating the agentic production trace and three held-out provider-real case runs"
  (cd "$repo_root/apps/api" && uv run python ../../scripts/evaluate-commercial-ai-case.py evaluate \
    --portfolio-version "$portfolio_version" \
    --evidence "$evidence_path" --output "$report_path")
}

run_staging() {
  require_phase load
  export ASF_HOMOLOGATION_GLOBAL_BUDGET_USD="${ASF_PRODUCTION_E2E_COST_CAP_USD:-50}"
  [ "${ASF_STAGING_READY:-0}" = "1" ] || die "Staging/VPS is not provisioned; market_ready remains blocked"
  require_confirmation ASF_PRODUCTION_E2E_REMOTE_CONFIRM RUN_AUTHORIZED_REMOTE_LOAD \
    "Staging validation needs explicit remote authorization"
  require_env ASF_RELEASE_API_BASE_URL
  require_env ASF_STAGING_CANARY_STARTED_AT
  require_env ASF_STAGING_CANARY_FINISHED_AT
  python3 - "${ASF_STAGING_CANARY_STARTED_AT}" "${ASF_STAGING_CANARY_FINISHED_AT}" <<'PY'
from datetime import datetime
import sys
start = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
finish = datetime.fromisoformat(sys.argv[2].replace("Z", "+00:00"))
if (finish - start).total_seconds() < 72 * 3600:
    raise SystemExit("The assisted staging canary must cover at least 72 hours")
PY
  "$repo_root/scripts/vps-docker-validate.sh" 2>&1 | tee "$evidence_root/staging.log"
  ASF_PRODUCTION_E2E_ALLOW_REMOTE=1 run_final_check
  mark_phase staging "$evidence_root/staging.log"
}

case "$phase" in
  check) run_final_check ;;
  preflight) run_preflight ;;
  local) run_local ;;
  human) run_human ;;
  load) run_load ;;
  rotate-credential) run_rotate_credential ;;
  staging) run_staging ;;
  pilot-final)
    for dependency in preflight local human load credential-rotation; do require_phase "$dependency"; done
    run_agentic_journey_evaluation
    run_workflow_candidate_evaluation
    run_commercial_ai_case_evaluation
    run_final_check internal_assisted_pilot_ready
    mark_phase pilot-final "$evidence_root/production-readiness-gate.json"
    ;;
  final)
    for dependency in preflight local human load credential-rotation staging; do require_phase "$dependency"; done
    run_agentic_journey_evaluation
    run_workflow_candidate_evaluation
    run_commercial_ai_case_evaluation
    run_final_check market_ready
    mark_phase final "$evidence_root/production-readiness-gate.json"
    ;;
  *) die "usage: $0 [check|preflight|local|human|load|rotate-credential|pilot-final|staging|final]" ;;
esac
