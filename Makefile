.PHONY: docker-doctor docker-full-up docker-full-validate docker-full-down docker-shell local-full-up local-full-validate local-full-down token-cost-simulation production-e2e-check production-e2e-pilot-check production-e2e-preflight production-e2e-local production-e2e-human production-e2e-load production-e2e-pilot-final production-e2e-staging production-e2e-final production-e2e-execute vps-docker-up vps-docker-validate vps-docker-down

docker-doctor:
	./scripts/docker-doctor.sh

docker-full-up:
	./scripts/docker-control.sh ./scripts/local-full-infra-up.sh

docker-full-validate:
	./scripts/docker-control.sh ./scripts/local-full-infra-validate.sh

docker-full-down:
	./scripts/docker-control.sh ./scripts/local-full-infra-down.sh

docker-shell:
	./scripts/docker-control.sh bash

local-full-up:
	./scripts/local-full-infra-up.sh

local-full-validate:
	./scripts/local-full-infra-validate.sh

local-full-down:
	./scripts/local-full-infra-down.sh

token-cost-simulation:
	cd apps/api && uv run python ../../scripts/simulate_portfolio_token_costs.py

production-e2e-check:
	./scripts/run-production-e2e-gate.sh check

production-e2e-pilot-check:
	ASF_PRODUCTION_E2E_TARGET=internal_assisted_pilot_ready ./scripts/run-production-e2e-gate.sh check

production-e2e-preflight:
	./scripts/run-production-e2e-gate.sh preflight

production-e2e-local:
	./scripts/run-production-e2e-gate.sh local

production-e2e-human:
	./scripts/run-production-e2e-gate.sh human

production-e2e-load:
	./scripts/run-production-e2e-gate.sh load

production-e2e-pilot-final:
	./scripts/run-production-e2e-gate.sh pilot-final

production-e2e-staging:
	./scripts/run-production-e2e-gate.sh staging

production-e2e-final:
	./scripts/run-production-e2e-gate.sh final

production-e2e-execute:
	./scripts/run-production-e2e-gate.sh preflight
	./scripts/run-production-e2e-gate.sh local
	./scripts/run-production-e2e-gate.sh human
	./scripts/run-production-e2e-gate.sh load
	./scripts/run-production-e2e-gate.sh staging
	./scripts/run-production-e2e-gate.sh final

vps-docker-up:
	./scripts/vps-docker-up.sh

vps-docker-validate:
	./scripts/vps-docker-validate.sh

vps-docker-down:
	./scripts/vps-docker-down.sh
