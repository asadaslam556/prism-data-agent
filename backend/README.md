# Backend

![Python](https://img.shields.io/badge/Python_3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?logo=langgraph&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?logo=sqlalchemy&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)

The FastAPI service that hosts the agent. Setup and configuration are in the
[root README](../README.md); [docs/guide.md](../docs/guide.md) goes through
every module.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env                                # optional, defaults run on Ollama
uvicorn app.main:app --reload --port 8000           # run
python -m pytest                                    # test (no model needed)
ruff check app tests list_models.py                 # lint
```

Interactive API docs are at http://localhost:8000/docs while it's running.

## Endpoints

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness, version, and the active provider and model |
| `GET` | `/api/sample` | Loads the bundled sales dataset into a new session |
| `POST` | `/api/upload` | CSV or TSV upload, becomes a new session |
| `POST` | `/api/connect` | Connects a SQLAlchemy database URL (off in the deployment image) |
| `GET` | `/api/dataset/{session_id}` | Schema and sample rows for a session |
| `POST` | `/api/query` | Runs the agent and returns the whole result |
| `POST` | `/api/query/stream` | Runs the agent and streams each step as Server-Sent Events |

## Layout

| Path | Contents |
| --- | --- |
| `app/agent/` | The orchestrator and worker graphs, state, prompts, LLM providers |
| `app/skills/` | SQL, pandas, chart and final-answer capabilities |
| `app/hooks/` | SQL and Python guardrails, step budget, logging |
| `app/services/` | Dataset sessions and the execution sandbox |
| `app/data/` | SQLAlchemy engines and schema introspection |
| `data/samples/` | The bundled sales dataset |
| `list_models.py` | Lists the models your configured endpoint serves |
