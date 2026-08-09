# Contributing

Thanks for looking at the code. Here's the short version of how to work on it.

## Setup

Backend: `cd backend && python -m venv .venv`, activate it, then
`pip install -r requirements-dev.txt`. Frontend: `cd frontend && npm install`.
You only need Ollama running to use the app; the test suite mocks the LLM.

## Before you open a PR

```bash
cd backend
ruff check app tests list_models.py   # lint
python -m pytest         # all of it, no network needed
cd ../frontend
npm run build            # catches JSX/JS breakage
```

CI runs exactly these on Python 3.11 and 3.12, so if they pass locally you're
in good shape.

## What goes where

- New agent capability -> `backend/app/skills/` (see the pattern in any skill,
  then register it in `skills/__init__.py`, add a node in `agent/graph.py`,
  and mention it in the planner prompt).
- New LLM provider -> one builder function in `backend/app/agent/providers.py`
  with `@register("name")` on it. Keep heavy SDK imports inside the function.
- Guardrail changes -> `backend/app/hooks/safety.py`, and please add tests.
  This file is the reason the app is safe to point at real data.

## Style

Ruff is the linter and the config lives in `pyproject.toml`. Match the
surrounding code, keep comments short, and don't add dependencies without a
reason you can defend in the PR description.
