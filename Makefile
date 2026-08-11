# aifw — Developer Makefile

.PHONY: install test test-v lint clean help

PYTHON := python3
PIP    := pip

help:
	@echo "Available targets:"
	@echo "  install   — pip install -e '.[dev]'"
	@echo "  test      — pytest (quiet)"
	@echo "  test-v    — pytest (verbose)"
	@echo "  lint      — ruff check"
	@echo "  clean     — remove __pycache__ + .pytest_cache"

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ --tb=short -q

test-v:
	$(PYTHON) -m pytest tests/ --tb=short -v

# `ruff format --check` gehoert dazu, weil die CI (_ci-pypi.yml) genau das
# zusaetzlich faehrt. Ohne diese Zeile war `make lint` lokal gruen und der
# Lint-Job trotzdem rot — einmal real passiert (PR #39, cost.py).
# Auch der Pfad ist bewusst `.` statt `src/ tests/`: die CI prueft das ganze Repo.
lint:
	ruff check .
	ruff format --check .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
	@echo "Cleaned."
