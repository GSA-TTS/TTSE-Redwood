.PHONY: help test test-cov lint lint-fix

PYTHON ?= .venv/bin/python
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
COV_TARGET ?= src/redwood_dataagent
TEST ?=
K ?=
PYTEST_ARGS ?=

help:
	@echo "Available targets:"
	@echo "  make test                      # Run all tests"
	@echo "  make test TEST=tests/test_query_adapter.py"
	@echo "  make test K='sender_workflow'  # Run tests matching -k expression"
	@echo "  make test PYTEST_ARGS='-x -vv'"
	@echo "  make test-cov                  # Run tests with terminal coverage"
	@echo "  make test-cov TEST=tests/test_storage/test_conventions.py"
	@echo "  make test-cov PYTEST_ARGS='-x -vv'"
	@echo "  make lint                      # Check code style with Ruff"
	@echo "  make lint-fix                  # Auto-fix code style issues"

# Run pytest without coverage. Supports optional TEST, K, and PYTEST_ARGS vars.
test:
	$(PYTEST) $(TEST) $(if $(K),-k "$(K)") $(PYTEST_ARGS)

# Run pytest with coverage. Supports optional TEST, K, and PYTEST_ARGS vars.
test-cov:
	$(PYTEST) $(TEST) $(if $(K),-k "$(K)") \
		--cov=$(COV_TARGET) --cov-report=term-missing --cov-report=xml:coverage/coverage.xml \
		$(PYTEST_ARGS)

# Lint code with Ruff (check only)
lint:
	$(RUFF) check src tests

# Auto-fix linting issues with Ruff
lint-fix:
	$(RUFF) check --fix src tests
	$(RUFF) format src tests
