VENV := $(abspath ../workspace/viewer/venv)
UV := $(VENV)/bin/uv
PYTHON := $(VENV)/bin/python
export UV_PROJECT_ENVIRONMENT := $(VENV)

.PHONY: setup migrate import watch dev frontend-dev build check test contracts serve
setup:
	python -m venv $(VENV)
	$(VENV)/bin/pip install 'uv==0.13.6'
	$(UV) sync --project backend --locked
	cd frontend && npm ci
migrate:
	$(VENV)/bin/alembic -c backend/alembic.ini upgrade head
import:
	$(VENV)/bin/quest-viewer import --site trace-viewer
watch:
	$(VENV)/bin/quest-viewer watch --site trace-viewer
contracts:
	$(PYTHON) scripts/export-openapi.py
	cd frontend && npm run generate
build:
	cd frontend && npm run build
check:
	$(VENV)/bin/ruff check backend scripts
	$(VENV)/bin/ruff format --check backend scripts
	cd frontend && npm run lint && npm run typecheck
test:
	$(VENV)/bin/pytest backend/tests
	cd frontend && npm test
dev:
	$(VENV)/bin/uvicorn quest_viewer.app:create_app --factory --host 127.0.0.1 --port 6081 --reload --reload-dir backend/src
frontend-dev:
	cd frontend && npm run dev
serve:
	$(PYTHON) serve.py
