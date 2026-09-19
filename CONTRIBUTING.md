# Contributing

Thanks for taking a look. Here's how to work on it.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setup

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Frontend:

```bash
cd frontend
npm install
```

You only need Ollama (or a hosted provider key) to use the app. The test suite mocks the model.

## Before opening a PR

```bash
cd backend
ruff check app tests list_models.py
python -m pytest
cd ../frontend
npm run build
```

CI runs the same checks on Python 3.11 and 3.12, plus a build of the deployment image, so if they pass locally you're in good shape.

## Where things go

- **A new agent capability** goes in `backend/app/skills/`. Copy the shape of an existing skill, add a node for it in `agent/graph.py`, and add the action to the planner prompt in `agent/prompts.py`.
- **A new LLM provider** is one builder function in `backend/app/agent/providers.py` with `@register("name")` on it. Keep the SDK import inside the function.
- **Guardrail changes** go in `backend/app/hooks/safety.py` or `backend/app/services/sandbox.py`, and need tests. These two files are what make it reasonable to point the app at real data. If you find a way past them, see [SECURITY.md](SECURITY.md) before opening a public issue.

## Style

Ruff is the linter; its config is in `backend/pyproject.toml`. Match the surrounding code, keep comments short and about *why*, and don't add a dependency without a reason you can explain in the PR description. Add a line to [CHANGELOG.md](CHANGELOG.md) for anything user-visible.
