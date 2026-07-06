.PHONY: docker-full-up docker-full-validate docker-full-down docker-shell local-full-up local-full-validate local-full-down vps-docker-up vps-docker-validate vps-docker-down

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

vps-docker-up:
	./scripts/vps-docker-up.sh

vps-docker-validate:
	./scripts/vps-docker-validate.sh

vps-docker-down:
	./scripts/vps-docker-down.sh
