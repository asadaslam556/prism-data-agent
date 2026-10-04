# Configuration

Every backend setting is an environment variable, read by `backend/app/config.py`. This page lists all of them with their defaults.

## Where settings come from

1. **`backend/.env`**: copy `backend/.env.example` and edit it. It's found relative to the `backend/` folder, whichever directory you start the server from.
2. **Real environment variables**, which override the file.

Settings are read once, at startup. `uvicorn --reload` only watches `.py` files, so restart the server after changing `.env`.

| Shell | Setting a variable for the current terminal |
| --- | --- |
| bash, zsh | `export LLM_PROVIDER=openai` |
| PowerShell | `$env:LLM_PROVIDER="openai"` |
| Docker (single image) | `docker run --env-file backend/.env ...` |
| docker compose | Only `LLM_PROVIDER`, `OLLAMA_MODEL` and `OLLAMA_BASE_URL` are passed to the backend; `backend/.env` is ignored |

## Model

| Variable | Default | What it does |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | `ollama`, or `openai` for OpenAI and any OpenAI-compatible API |
| `LLM_MODEL` | (unset) | Model for the active provider; overrides the defaults below |
| `LLM_TEMPERATURE` | `0.0` | Blank, `none`, `off` or `unset` leaves it out of the request. The old name `OLLAMA_TEMPERATURE` also works |
| `LLM_TOP_P` | (unset) | Nucleus sampling for OpenAI-compatible APIs; blank leaves it to the provider |
| `LLM_MAX_TOKENS` | `2048` | Cap on each response |
| `LLM_REQUEST_TIMEOUT` | `180` | Seconds per model call. The old name `OLLAMA_REQUEST_TIMEOUT` also works |
| `LLM_EXTRA_BODY` | (unset) | JSON object merged into OpenAI-compatible requests. Required for DeepSeek: `{"thinking": {"type": "disabled"}}` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama listens |
| `OLLAMA_MODEL` | `qwen2.5` | Ollama's model when `LLM_MODEL` is unset; blank means the default |
| `OPENAI_API_KEY` | (unset) | Key for the `openai` provider; use `<YOUR_API_KEY>`, never commit it |
| `OPENAI_BASE_URL` | (unset) | Any OpenAI-compatible endpoint, such as `https://api.deepseek.com/v1` |
| `OPENAI_MODEL` | (unset) | Used when `LLM_MODEL` is unset, but only from the real environment, not `backend/.env`. The default is `gpt-4o-mini` |

More in [models.md](models.md).

## Agent

| Variable | Default | What it does |
| --- | --- | --- |
| `MAX_AGENT_STEPS` | `16` | Planner steps for one question, shared by all its branches |
| `MAX_PARALLEL_BRANCHES` | `3` | Sub-questions run at once; `1` gives a single plan-act loop |
| `MAX_VERIFY_PASSES` | `1` | How many times the verifier may send work back |
| `ENABLE_VERIFIER` | `true` | Turns the verification step off entirely |
| `MAX_SQL_ROWS` | `1000` | Row cap added to, or clamped on, every query |
| `SQL_RETRY_ATTEMPTS` | `1` | Extra tries after a rejected or failed query |
| `SANDBOX_TIMEOUT_SECONDS` | `30` | Wall-clock cap on one generated snippet |

## Server

| Variable | Default | What it does |
| --- | --- | --- |
| `APP_USERNAME`, `APP_PASSWORD` | (blank) | Set both to put every route except `/api/health` behind an HTTP Basic login. Set them on anything with a public URL |
| `ENABLE_DB_CONNECT` | `true` | Allows `/api/connect`. The deployment image sets `false`, because it dials any URL it's given |
| `MAX_UPLOAD_MB` | `25` | Largest accepted upload |
| `MAX_SESSIONS` | `24` | Datasets kept loaded; past this the least recently used goes |
| `SESSION_TTL_MINUTES` | `120` | Idle time before a dataset is dropped |
| `CORS_ORIGINS` | `["http://localhost:5173", "http://127.0.0.1:5173"]` | Origins allowed to call the API from another host, as a JSON list |
| `LOG_LEVEL` | `INFO` | The app's log level |

## Paths

Rarely changed; useful when packaging Prism differently.

| Variable | Default | What it does |
| --- | --- | --- |
| `FRONTEND_DIST_PATH` | `backend/static` | Built frontend to serve; skipped when the folder doesn't exist, as in local development |
| `SAMPLE_DATA_PATH` | `backend/data/samples/sales.csv` | The bundled sample |
| `DEFAULT_TABLE_NAME` | `data` | Table name for uploads and the sample |

## Frontend

| Variable | Default | What it does |
| --- | --- | --- |
| `VITE_API_BASE` | (empty) | Backend URL, only for a split deployment. Leave it empty with the Vite proxy, nginx or the single image. Copy `frontend/.env.example` to `frontend/.env` to set it |

## Small machines

On a host with 512 MB of memory, such as Render's free tier, lower `MAX_UPLOAD_MB` (5), `MAX_SESSIONS` (3) and `MAX_PARALLEL_BRANCHES` (2). pandas, numpy, matplotlib, LangChain and SQLAlchemy use roughly 300 MB before any data is loaded.
