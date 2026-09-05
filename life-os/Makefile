# Life OS — common tasks. Run these from the life-os/ directory.
.PHONY: help setup api web seed test lint build up down logs reset

VENV := api/.venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

setup: ## Create the API virtualenv and install web dependencies
	python3 -m venv $(VENV)
	$(PIP) install -q -r api/requirements-dev.txt
	cd web && npm install

api: ## Run the API on :8000 with reload
	cd api && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

web: ## Run the dev frontend on :5173
	cd web && npm run dev

seed: ## Create the first account with demo data (EMAIL=... PASSWORD=...)
	cd api && ../$(VENV)/bin/python -m app.seed \
		--email "$(or $(EMAIL),you@example.com)" \
		--password "$(or $(PASSWORD),change-me-please-123)" --demo

test: ## Run the API test suite
	cd api && ../$(VENV)/bin/python -m pytest -q

typecheck: ## Typecheck the frontend
	cd web && npm run typecheck

build: ## Production build of the frontend
	cd web && npm run build

up: ## Start the Docker stack
	docker compose up -d --build

down: ## Stop the Docker stack
	docker compose down

logs: ## Tail Docker logs
	docker compose logs -f --tail=100

reset: ## Delete the local SQLite database (keeps your keys)
	rm -f api/data/lifeos.db api/data/lifeos.db-wal api/data/lifeos.db-shm
