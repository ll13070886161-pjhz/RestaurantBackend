BOOTSTRAP_PYTHON ?= python3
PYTHON ?= python3
HOST ?= 0.0.0.0
PORT ?= 8000

.PHONY: init check db-check dev prod test migrate-mysql

ifneq ("$(wildcard .venv/bin/python)","")
PYTHON := .venv/bin/python
endif

init:
	@if [ ! -x ".venv/bin/python" ]; then \
	  echo "Creating virtualenv at .venv..."; \
	  $(BOOTSTRAP_PYTHON) -m venv .venv; \
	fi
	cp -n .env.example .env || true
	.venv/bin/python -m pip install -U pip
	.venv/bin/python -m pip install -r requirements.txt

check:
	$(PYTHON) scripts/check_env.py

db-check:
	$(PYTHON) scripts/check_db.py

dev:
	$(MAKE) check
	$(PYTHON) -m uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

prod:
	$(MAKE) check
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT)

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="." $(PYTHON) -m pytest -q tests

migrate-mysql:
	$(PYTHON) scripts/migrate_sqlite_to_mysql.py
