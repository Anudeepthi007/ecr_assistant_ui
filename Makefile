# ECR Intelligence Agent - developer entry points.
.DEFAULT_GOAL := help
PY := .venv/Scripts/python.exe
ifeq ($(OS),)
PY := .venv/bin/python
endif

.PHONY: help
help: ## Show the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: venv
venv: ## Create the virtualenv and install backend dependencies
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r backend/requirements.txt

.PHONY: seed
seed: ## Create the schema and load the sample corpus
	cd backend && ../$(PY) -m app.seed

.PHONY: backend
backend: ## Run the API on :8000 with reload
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

.PHONY: frontend
frontend: ## Run the dashboard on :3000
	cd frontend && yarn start

.PHONY: install-frontend
install-frontend: ## Install frontend dependencies
	cd frontend && yarn install

.PHONY: test
test: ## Run the backend test suite
	cd backend && ../$(PY) -m pytest -n 0 -q

.PHONY: demo
demo: ## Run the demo analysis against a running backend
	$(PY) scripts/demo.py

.PHONY: docker
docker: ## Build and start the whole stack
	docker compose up --build

.PHONY: docker-down
docker-down: ## Stop the stack and drop volumes
	docker compose down -v

.PHONY: lint
lint: ## Byte-compile every backend module (fast syntax gate)
	$(PY) -m compileall -q backend/app
