.PHONY: help bootstrap ensure-dev-env test test-cov lint lint-fix sonar-prepare sonar-setup sonar-local sonar-maintainability pre-pr

PYTHON ?= .venv/bin/python
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
COV_TARGET ?= src/redwood_dataagent
SONAR_SCANNER ?= sonar-scanner
SONAR_PROJECT_SETTINGS ?= sonar-project.properties
SONAR_HOST_URL ?= https://sonarqube-ce.prod.core.mcaas.fcs.gsa.gov/
SONAR_SETUP_SCRIPT ?= ./make-sonar-setup
SONAR_ISSUES_SCRIPT ?= ./scripts/sonar_maintainability_issues.py
SONAR_PROJECT_KEY ?= ttse-redwood
SONAR_EXTRA_ARGS ?=
TEST ?=
K ?=
PYTEST_ARGS ?=

help:
	@echo "Available targets:"
	@echo "  make bootstrap                 # Create .venv and install runtime+test deps"
	@echo "  make test                      # Run all tests"
	@echo "  make test TEST=tests/test_query_adapter.py"
	@echo "  make test K='sender_workflow'  # Run tests matching -k expression"
	@echo "  make test PYTEST_ARGS='-x -vv'"
	@echo "  make test-cov                  # Run tests with terminal coverage"
	@echo "  make test-cov TEST=tests/test_storage/test_conventions.py"
	@echo "  make test-cov PYTEST_ARGS='-x -vv'"
	@echo "  make lint                      # Check code style with Ruff"
	@echo "  make lint-fix                  # Auto-fix code style issues"
	@echo "  make sonar-setup               # Install SonarScanner via Homebrew if missing"
	@echo "  make sonar-local               # Run Sonar scan locally (with fresh coverage)"
	@echo "  make sonar-maintainability     # List open Sonar maintainability issues (code smells)"
	@echo "  make pre-pr                    # Run lint and local Sonar scan"

# One-time local setup for new machines/contributors.
bootstrap:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e '.[test]'

# Ensure required runtime/test dependencies are present in the selected venv.
ensure-dev-env:
	@test -x "$(PYTHON)" || (echo "$(PYTHON) not found. Run 'make bootstrap' first." && exit 1)
	@$(PYTHON) -c "import fastapi, pytest" >/dev/null 2>&1 || (echo "Installing missing dependencies into .venv ..." && $(PYTHON) -m pip install -e '.[test]')

# Run pytest without coverage. Supports optional TEST, K, and PYTEST_ARGS vars.
test: ensure-dev-env
	$(PYTEST) $(TEST) $(if $(K),-k "$(K)") $(PYTEST_ARGS)

# Run pytest with coverage. Supports optional TEST, K, and PYTEST_ARGS vars.
test-cov: ensure-dev-env
	$(PYTEST) $(TEST) $(if $(K),-k "$(K)") \
		--cov=$(COV_TARGET) --cov-report=term-missing --cov-report=xml:coverage/coverage.xml \
		$(PYTEST_ARGS)

# Lint code with Ruff (check only)
lint: ensure-dev-env
	$(RUFF) check src tests

# Auto-fix linting issues with Ruff
lint-fix: ensure-dev-env
	$(RUFF) check --fix src tests
	$(RUFF) format src tests

# Prepare local artifacts expected by sonar-scanner.
sonar-prepare:
	mkdir -p coverage empty

# Prepare local SonarScanner prerequisites.
sonar-setup:
	bash $(SONAR_SETUP_SCRIPT)

# Run local Sonar scan using native sonar-scanner binary.
# This target generates fresh coverage first to avoid stale/partial reports.
sonar-local: test-cov sonar-setup sonar-prepare
	@test -n "$(SONAR_HOST_URL)" || (echo "SONAR_HOST_URL is required" && exit 1)
	@test -n "$(SONAR_TOKEN)" || (echo "SONAR_TOKEN is required" && exit 1)
	@command -v $(SONAR_SCANNER) >/dev/null 2>&1 || (echo "$(SONAR_SCANNER) is not installed. Run 'make sonar-setup'." && exit 1)
	$(SONAR_SCANNER) \
		-Dproject.settings=$(SONAR_PROJECT_SETTINGS) \
		-Dsonar.host.url=$(SONAR_HOST_URL) \
		-Dsonar.token=$(SONAR_TOKEN) \
		$(SONAR_EXTRA_ARGS)

# Print open Sonar maintainability/code smell issues for local fixing.
sonar-maintainability:
	@test -n "$(SONAR_HOST_URL)" || (echo "SONAR_HOST_URL is required" && exit 1)
	@test -n "$(SONAR_TOKEN)" || (echo "SONAR_TOKEN is required" && exit 1)
	$(PYTHON) $(SONAR_ISSUES_SCRIPT) --host-url "$(SONAR_HOST_URL)" --token "$(SONAR_TOKEN)" --project-key "$(SONAR_PROJECT_KEY)"

# Pre-PR local quality gate: lint + coverage + sonar.
pre-pr: lint sonar-local
