# Contributing

![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff&logoColor=black)
![Vitest](https://img.shields.io/badge/Vitest-6E9F18?logo=vitest&logoColor=white)
![ESLint](https://img.shields.io/badge/ESLint-4B32C3?logo=eslint&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white)

Thanks for taking a look. Here's how to work on it. How the code fits together is in [docs/architecture.md](docs/architecture.md).

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

## How a change lands

![How a change lands](docs/images/ci.svg)

## Before opening a PR

```bash
cd backend
ruff check app tests list_models.py
python -m pytest
cd ../frontend
npm run lint
npm test
npm run build
```

CI runs the same checks on Python 3.11 and 3.12, plus a build of the deployment image and a CodeQL scan, so if they pass locally you're in good shape. `main` only accepts changes that pass all of them, and PRs are squash-merged.

## Where things go

- **A new agent capability** goes in `backend/app/skills/`. Copy the shape of an existing skill, add a node for it in `agent/graph.py`, add the action to the planner prompt in `agent/prompts.py`, and add the node name to `TraceStep.node` in `schemas.py`. The full steps are in the [README](README.md#extending-it).
- **A new LLM provider** is one builder function in `backend/app/agent/providers.py` with `@register("name")` on it. Keep the SDK import inside the function.
- **Guardrail changes** go in `backend/app/hooks/safety.py` or `backend/app/services/sandbox.py`, and need tests. These two files are what make it reasonable to point the app at real data. If you find a way past them, see [SECURITY.md](SECURITY.md) before opening a public issue.

## Style

Ruff lints the backend (config in `backend/pyproject.toml`) and ESLint the frontend (`frontend/eslint.config.js`). Match the surrounding code, keep comments short and about *why*, and don't add a dependency without a reason you can explain in the PR description. Add a line to [CHANGELOG.md](CHANGELOG.md) for anything user-visible.
