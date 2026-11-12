# AI Job Search - container command shortcuts.
#
# Run `make` or `make help` for the target list.
# Requires Docker Desktop to be running. Works from PowerShell, cmd, Git Bash
# and WSL (single-line recipes only, so no POSIX shell is required).

COMPOSE ?= docker compose
AGENT := $(COMPOSE) run --rm agent
PYTHON ?= python

.DEFAULT_GOAL := help
.PHONY: help build rebuild agent shell login test lint verify model models doctor upstream auth gh-status telegram-up telegram-down telegram-status db-migrate db-backup db-check db-stats down clean clean-all

help:
	@echo AI Job Search - available targets:
	@echo ----------------------------------------
	@echo   make build      Build the agent image
	@echo   make rebuild    Rebuild the image with the latest base images
	@echo   make agent      OpenCode TUI in the container
	@echo   make shell      Bash shell inside the container
	@echo   make login      Refresh the hh.ru session (host-side, needs a display)
	@echo   make test       Run the Python test suite in the container
	@echo   make lint       Run skill lint and security guards
	@echo   make verify     Compile the example CV, verify its PDF
	@echo   make model      Health-check the selected model service
	@echo   make models     Show the resolved service, model and base URL
	@echo   make doctor     Show toolchain versions and isolation facts
	@echo   make upstream   Preview which upstream framework files changed
	@echo   make auth       Log in to an additional OpenCode provider
	@echo   make gh-status  Show GitHub auth status in the container
	@echo   make telegram-up  Start the Telegram bot (aiogram)
	@echo   make telegram-down  Stop the Telegram bot
	@echo   make telegram-status  Show the bot configuration summary
	@echo   make db-migrate   Initialise/upgrade the SQLite state database
	@echo   make db-backup    Back up the SQLite state database
	@echo   make db-check     Show database schema and data quality
	@echo   make db-stats     Print the weekly metrics to the terminal
	@echo   make down       Stop containers (keeps the volume and the image)
	@echo   make clean      Remove containers and the local image
	@echo   make clean-all  Also remove the agent-home volume (auth/sessions!)
	@echo ----------------------------------------
	@echo Full command reference: CHEATSHEET.md

build:
	$(COMPOSE) build

rebuild:
	$(COMPOSE) build --pull

agent:
	$(AGENT)

shell:
	$(AGENT) bash

login:
	$(PYTHON) tools/hh_apply.py login

test:
	$(AGENT) bash -lc "cd /work && python3 -m unittest discover -s tests -t ."

lint:
	$(AGENT) bash -lc "cd /work && python3 tools/lint_skills.py && python3 tools/security_guards.py"

verify:
	$(AGENT) bash -lc "cd /work/cv && lualatex -interaction=nonstopmode -halt-on-error main_example.tex >/dev/null && cd /work && python3 tools/verify_pdf.py cv/main_example.pdf --min-chars 100"

model:
	$(AGENT) bash -lc "python3 tools/render_opencode_config.py --check || true"

models:
	$(AGENT) bash -lc "python3 tools/render_opencode_config.py --list"

doctor:
	$(AGENT) bash -lc "id && bun --version && python3 --version && opencode --version && lualatex --version | head -n1 && grep -E 'Cap(Eff|Prm)' /proc/self/status"

upstream:
	$(AGENT) bash -lc "cd /work && git fetch upstream --tags && python3 tools/check_upstream_updates.py"

auth:
	$(AGENT) opencode auth login

gh-status:
	$(AGENT) bash -lc "gh auth status || true"

db-migrate:
	$(AGENT) bash -lc "cd /work && python3 tools/state_db.py init"

db-backup:
	$(AGENT) bash -lc "cd /work && python3 tools/state_db.py backup"

db-check:
	$(AGENT) bash -lc "cd /work && python3 tools/state_db.py schema && python3 tools/state_db.py quality"

db-stats:
	$(AGENT) bash -lc "cd /work && python3 tools/state_db.py stats --format markdown"

telegram-up:
	$(COMPOSE) up -d telegram-gateway

telegram-down:
	$(COMPOSE) stop telegram-gateway

telegram-status:
	$(COMPOSE) run --rm telegram-gateway status

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) down --rmi local

clean-all:
	$(COMPOSE) down --rmi local --volumes
