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

# Deckungsgleich mit dem CI-Lint-Job (_ci-pypi.yml): der faehrt `ruff check .`
# UND `ruff format --check .`. Solange hier nur `ruff check src/ tests/` stand,
# konnte `make lint` gruen sein und der Job trotzdem rot — einmal real passiert
# (PR #39: zwei fehlende Leerzeilen in cost.py/service.py, lokal unsichtbar).
# Wer den Umfang hier aendert, aendert ihn auch dort — sonst faellt die Luecke
# wieder erst in der CI auf.
lint:
	ruff check .
	ruff format --check .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
	@echo "Cleaned."

# Fleet-Standard-Einstieg (pkg-agents-v1, platform #2075 K2): make setup && make test
setup:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]" || .venv/bin/pip install -e .
	.venv/bin/pip install pytest
