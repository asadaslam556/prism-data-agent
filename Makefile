# Convenience targets (macOS / Linux / Windows via Git Bash or WSL).
# On plain Windows PowerShell, run the underlying commands directly - they are
# all listed in the README.

.PHONY: help install-backend install-frontend backend frontend test lint

help:
	@echo "make install-backend   - create venv + install backend deps"
	@echo "make install-frontend  - npm install"
	@echo "make backend           - run the FastAPI server (port 8000)"
	@echo "make frontend          - run the Vite dev server (port 5173)"
	@echo "make test              - run the backend and frontend tests"
	@echo "make lint              - lint the backend (ruff) and frontend (eslint)"

install-backend:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && \
	pip install -r requirements-dev.txt

install-frontend:
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && . .venv/bin/activate && python -m pytest
	cd frontend && npm test

lint:
	cd backend && . .venv/bin/activate && ruff check app tests list_models.py
	cd frontend && npm run lint
