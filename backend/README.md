# Backend

FastAPI service hosting the LangGraph agent. See the root README for setup and
`docs/architecture.md` for the internals.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000           # run
python -m pytest                                    # test (no Ollama needed)
ruff check app tests list_models.py                 # lint
```

Interactive API docs at http://localhost:8000/docs once running.