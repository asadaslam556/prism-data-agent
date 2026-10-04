# Deployment

Prism runs three ways. All of them serve the same backend; they differ in who serves the frontend and where the model lives.

[![Three ways to run Prism](diagrams/deployment.architecture.svg)](diagrams/deployment.architecture.html)

| Setup | Files | Frontend served by | Model | Port |
| --- | --- | --- | --- | --- |
| Local development | none | Vite dev server, proxying `/api` to `localhost:8000` | Ollama on the host, or a hosted API | 5173 (app), 8000 (API) |
| docker compose | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf` | nginx, proxying `/api/` to the backend container | Ollama in its own container | 5173 (app), 8000 (API), 11434 (Ollama) |
| Single image | `Dockerfile` | FastAPI itself, from `static/` | A hosted API, from `--env-file` or the host's settings | `$PORT`, or 7860 |

## Local development

The two-terminal setup in the [README quickstart](../README.md#quickstart), or [windows.md](windows.md) for PowerShell.

## docker compose

```bash
docker compose up --build
docker compose exec ollama ollama pull qwen2.5   # once
```

Open http://localhost:5173. The backend only receives `LLM_PROVIDER`, `OLLAMA_MODEL` and `OLLAMA_BASE_URL`; `backend/.env` is never copied into the image, so the stack always runs on Ollama. nginx turns proxy buffering off for `/api/`, which streaming needs, and allows 300 seconds per request.

## Single image

```bash
docker build -t prism .
docker run --rm -p 7860:7860 --env-file backend/.env prism
```

Open http://localhost:7860. A two-stage build: Node 20 builds the frontend, then a Python 3.12 image runs uvicorn as a non-root user (uid 1000) and serves the API and the built frontend from one origin, so there's no CORS to configure.

- It listens on `$PORT` when the host sets one, as Render, Cloud Run and Fly do, and 7860 otherwise.
- It sets `ENABLE_DB_CONNECT=false`, because `/api/connect` dials any URL it's given. Sample and CSV upload still work, and the app hides the database card.
- `.dockerignore` keeps every `.env` file out of the image. Keys come from `--env-file` or the host's secret settings.
- Anything with a public URL should set `APP_USERNAME` and `APP_PASSWORD` ([api.md](api.md#login)).

To deploy it on Render's free tier with DeepSeek, follow [deploy-render.md](deploy-render.md).

## CI

[![CI jobs](diagrams/ci.workflow.svg)](diagrams/ci.workflow.html)

`.github/workflows/ci.yml` runs on every pull request and every push to `main`, with read-only permissions:

| Job | Runs |
| --- | --- |
| `backend` (Python 3.11 and 3.12) | `pip install -r requirements-dev.txt`, `ruff check app tests list_models.py`, `python -m pytest`. The model is mocked, so no Ollama is needed |
| `frontend` | `npm ci`, `npm run build` on Node 20 |
| `image` | `docker build -t prism .`, so a broken Dockerfile fails here rather than on Render |

To run the same checks locally, see [CONTRIBUTING.md](../CONTRIBUTING.md).
