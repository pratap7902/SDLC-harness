PORT ?= 8791
PYTHON ?= /Users/Banji/.pyenv/versions/3.12.12/bin/python3.12
VENV := .venv
BIN := $(VENV)/bin

install:       ## venv + deps (override the interpreter: make install PYTHON=python3.12)
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r requirements-dev.txt

db:            ## start MySQL 8 (docker, port 3311; db `srs`, tests `srs_test`)
	docker compose up -d --wait db

migrate:       ## apply migrations to the configured DB (default: SQLite var/dev.db)
	@mkdir -p var
	$(BIN)/alembic upgrade head

check:         ## lint blueprint/*.yaml (types, vocab, lifecycle, rule ↔ code pairing)
	$(BIN)/python -m app.blueprint.services.blueprint_loader

dev: migrate   ## run the service with reload on :8791 (API /api · docs /docs · MCP /mcp)
	$(BIN)/uvicorn main:app --reload --port $(PORT) --timeout-graceful-shutdown 5

test:          ## the suite on in-memory SQLite
	$(BIN)/pytest -q

test-mysql:    ## the suite on MySQL (make db first)
	TEST_DATABASE_URL=mysql+mysqlconnector://root:srs@127.0.0.1:3311/srs_test $(BIN)/pytest -q

token:         ## mint a bearer token: make token ACTOR=runner-sdk KIND=agent [ROLES=ci] [LABEL=…] [DAYS=90]
	$(BIN)/python scripts/mint_token.py mint --actor "$(ACTOR)" --kind "$(KIND)" --roles "$(ROLES)" --label "$(LABEL)" --days "$(or $(DAYS),0)"

lint:
	$(BIN)/ruff check .

seed: migrate  ## load the demo scenario into the dev DB (wipes it first: SEED_KEEP=1 keeps it)
	$(BIN)/python scripts/seed_demo.py

frontend:      ## install (only when package-lock.json changed) + build the React app into frontend/dist
	cd frontend && h=$$(shasum package-lock.json | cut -d' ' -f1); \
	  if [ "$$(cat node_modules/.lock-hash 2>/dev/null)" != "$$h" ]; then \
	    npm ci --no-audit --no-fund && echo $$h > node_modules/.lock-hash; fi && \
	  npm run build

frontend-dev:  ## Vite dev server on :5173 (proxies /api to the backend on :8791; run make dev too)
	cd frontend && npm run dev

reset:         ## delete the SQLite dev DB
	rm -f var/dev.db

.PHONY: install db migrate check dev test test-mysql lint seed reset frontend frontend-dev token
