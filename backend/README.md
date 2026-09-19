# Backend

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

| Path | Contents |
| --- | --- |
| `app/agent/` | The orchestrator and worker graphs, state, prompts, LLM providers |
| `app/skills/` | SQL, pandas, chart and final-answer capabilities |
| `app/hooks/` | SQL and Python guardrails, step budget, logging |
| `app/services/` | Dataset sessions and the execution sandbox |
| `app/data/` | SQLAlchemy engines and schema introspection |
| `data/samples/` | The bundled sales dataset |
| `list_models.py` | Lists the models your configured endpoint serves |
