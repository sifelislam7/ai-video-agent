.PHONY: help install dev run test demo clean lint

PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

help:
	@echo "make install  — create .venv and install dependencies"
	@echo "make run      — start the web dashboard on http://localhost:8000"
	@echo "make dev      — same, with auto-reload"
	@echo "make test     — run the test suite"
	@echo "make demo     — generate one sample video from the CLI"
	@echo "make clean    — remove generated media and caches"

install:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	@test -f .env || cp .env.example .env
	@echo "✓ ready — edit .env then run 'make run'"

run:
	$(BIN)/python -m app.cli serve

dev:
	$(BIN)/python -m app.cli serve --reload

test:
	$(BIN)/python -m pytest -q

demo:
	$(BIN)/python -m app.cli create --topic "٣ عادات صباحية تضاعف تركيزك" --scenes 4 --seconds 24

clean:
	rm -rf data/output/* .pytest_cache **/__pycache__
	@echo "✓ cleaned"
