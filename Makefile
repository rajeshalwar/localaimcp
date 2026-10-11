# Local AI + MCP solar stack. Everything runs in containers; nothing here
# assumes a Linux host.
SHELL := /bin/bash
COMPOSE := podman compose

# Settings resolve as: command line / shell environment > .env > default.
# Make does not read .env on its own (compose does), and a plain `include .env`
# would both clobber shell overrides and keep the trailing whitespace before
# inline comments. So read one key at a time, trimmed.
envget = $(or $($(1)),$(shell sed -n 's/^$(1)=\([^\#]*\).*/\1/p' .env 2>/dev/null | tail -n 1 | xargs),$(2))

MODEL ?= $(call envget,MODEL_NAME,qwen2.5:7b-instruct)
# Fixed by `name:` in compose.yaml, so these do not depend on the clone's folder name.
NETINT ?= localaimcp_netint
AGENT_IMAGE ?= localhost/localaimcp_agent:latest

# Everything the agent reads. It runs on netint via `podman run`, not compose,
# so compose's own .env handling never reaches it.
AGENT_ENV = \
  -e OLLAMA_HOST=http://ollama:11434 \
  -e MCP_URL=http://appliance:8000/mcp \
  -e MODEL_NAME=$(MODEL) \
  -e OLLAMA_KEEP_ALIVE=$(call envget,OLLAMA_KEEP_ALIVE,-1) \
  -e OLLAMA_NUM_CTX=$(call envget,OLLAMA_NUM_CTX,8192) \
  -e OLLAMA_NUM_PREDICT=$(call envget,OLLAMA_NUM_PREDICT,350) \
  -e OLLAMA_TOOL_NUM_PREDICT=$(call envget,OLLAMA_TOOL_NUM_PREDICT,700) \
  -e OLLAMA_TIMEOUT=$(call envget,OLLAMA_TIMEOUT,240)

.DEFAULT_GOAL := help
.PHONY: help doctor setup build up down demo repl logs test \
        pull-model seed-cache check-nrel prove-isolation prove-egress \
        egress-report egress-reset bench systemd-status clean lock

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

doctor: ## Check the host can actually run this
	@echo "podman : $$(podman --version 2>/dev/null || echo MISSING)"
	@echo "compose: $$(podman compose version 2>/dev/null | tail -1 || echo MISSING)"
	@podman machine list 2>/dev/null | tail -n +1 || true
	@echo -n "cgroups: "; podman info --format '{{.Host.CgroupsVersion}} (rootless={{.Host.Security.Rootless}}, runtime={{.Host.OCIRuntime.Name}})'
	@echo -n "vm mem : "; podman info --format '{{.Host.MemTotal}}' | awk '{printf "%.1f GB\n", $$1/1073741824}'
	@echo -n "vm cpus: "; podman info --format '{{.Host.NCPUs}}'
	@echo -n "disk   : "; df -h / | awk 'NR==2{print $$4" free on host /"}'
	@test -f .env && echo ".env   : present" || echo ".env   : MISSING -- copy .env.example"

setup: build pull-model ## First run: build images and pull the model
	@echo "Setup complete. Now: make up && make demo"

build: ## Build the appliance and agent images
	$(COMPOSE) build

up: ## Start the stack (TOOL_PROFILE=granular|composite|all, REPLAY_ONLY=true)
	@# TOOL_PROFILE and REPLAY_ONLY are read by the MCP server, so they are set
	@# here, not on `make demo`. compose recreates the appliance when they change.
	$(COMPOSE) up -d appliance ollama
	@echo "waiting for the appliance to become healthy…"
	@for i in $$(seq 1 60); do \
	  s=$$(podman inspect appliance --format '{{.State.Health.Status}}' 2>/dev/null); \
	  [ "$$s" = "healthy" ] && { echo "appliance: healthy"; exit 0; }; sleep 2; done; \
	  echo "appliance did not become healthy; see: make logs"; exit 1
	@echo "server : profile=$$(podman exec appliance printenv TOOL_PROFILE)  replay_only=$$(podman exec appliance printenv REPLAY_ONLY)"

down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

demo: ## Interactive agent REPL (ARGS="a question" to ask once)
	@$(MAKE) --no-print-directory _check-timer
	@# NOTE: not `compose run`. podman-compose attaches `run` containers to the
	@# project's first network rather than the service's declared one, so the
	@# agent could not resolve `ollama`. Pinning the network makes it deterministic
	@# -- and keeps the agent on the internal network, with no route out.
	podman run --rm -i $$([ -t 0 ] && echo -t) --network $(NETINT) \
	  $(AGENT_ENV) $(AGENT_IMAGE) $(ARGS)

repl: demo ## Alias for demo

_check-timer:
	@s=$$(podman exec appliance systemctl is-enabled warm-cache.timer 2>/dev/null); \
	if [ "$$s" != "masked" ]; then \
	  echo "WARNING: warm-cache.timer is '$$s', not masked; it can add rows to egress_log."; \
	  echo "         podman exec appliance systemctl mask warm-cache.timer"; fi

logs: ## Follow appliance logs
	podman logs -f appliance

test: ## Run the offline test suite
	.venv/bin/python -m pytest

pull-model: ## Download the model into the shared volume (one-shot, networked)
	MODEL_NAME=$(MODEL) $(COMPOSE) --profile setup run --rm model-pull

seed-cache: ## Load committed fixtures so the demo works offline
	podman exec -e PYTHONPATH=/app/src appliance python3 -m scripts.seed_cache

check-nrel: ## Verify the NREL key and response shape (needs network)
	podman exec -e PYTHONPATH=/app/src appliance python3 -m scripts.check_nrel

prove-isolation: ## Show, structurally, that the model has no route out
	@echo "netint internal        : $$(podman network inspect localaimcp_netint --format '{{.Internal}}' 2>/dev/null || podman network inspect netint --format '{{.Internal}}')"
	@echo "ollama    networks     : $$(podman inspect ollama    --format '{{range $$k,$$v := .NetworkSettings.Networks}}{{$$k}} {{end}}')"
	@echo "appliance networks     : $$(podman inspect appliance --format '{{range $$k,$$v := .NetworkSettings.Networks}}{{$$k}} {{end}}')"
	@echo
	@echo "The model container is on the internal network only. That is a"
	@echo "property of the topology, not a promise from the application."

prove-egress: ## Contrast demo: appliance reaches the net, ollama cannot (needs network)
	@echo "Identical probe, run from two containers. The only difference is"
	@echo "which network each one is attached to."
	@echo
	@echo -n "  appliance -> example.com:443 : "
	@podman exec appliance bash -c 'exec 3<>/dev/tcp/example.com/443 && echo CONNECTED' 2>&1 | tail -1
	@echo -n "  ollama    -> example.com:443 : "
	@podman run --rm --network $$(podman inspect ollama --format '{{range $$k,$$v := .NetworkSettings.Networks}}{{$$k}}{{end}}') \
	  quay.io/fedora/fedora:41 bash -c 'exec 3<>/dev/tcp/example.com/443 && echo CONNECTED' 2>&1 | tail -1
	@echo
	@echo "  The container running the model has no route off this machine."

egress-report: ## Every byte that left this machine, this session
	podman exec -e PYTHONPATH=/app/src appliance python3 -m scripts.egress_report

egress-reset: ## Clear the egress log
	podman exec -e PYTHONPATH=/app/src appliance python3 -m scripts.egress_report --reset

bench: ## Measure turn latency (S7 gate). MODEL=... to compare models
	podman run --rm --network $(NETINT) $(AGENT_ENV) \
	  --entrypoint python3 $(AGENT_IMAGE) /app/scripts/bench.py --runs $${RUNS:-5}

systemd-status: ## Show the units running inside the appliance
	podman exec appliance systemctl list-units --type=service --no-pager
	@echo; podman exec appliance systemctl list-dependencies mcp-solar.service --no-pager

clean: ## Remove containers and volumes (destroys the cache)
	$(COMPOSE) down -v

lock: ## Re-resolve requirements.lock inside the image's base OS
	podman run --rm -v "$(CURDIR)/requirements.txt:/r.txt:ro,Z" quay.io/fedora/fedora:44 sh -c \
	  'dnf -y -q install --setopt=install_weak_deps=False python3 python3-pip >/dev/null && \
	   python3 -m venv /v && /v/bin/pip install -q -r /r.txt >/dev/null && /v/bin/pip freeze' \
	  | { printf '# Exact versions the container images install, resolved on Fedora 44 / Python 3.14.\n# requirements.txt holds the ranges; regenerate this after changing it:\n#   make lock\n'; grep '=='; } > requirements.lock
