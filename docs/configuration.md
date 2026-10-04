# Configuration and API

![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?logo=ollama&logoColor=white)
![OpenAI compatible](https://img.shields.io/badge/OpenAI--compatible-412991)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

Every backend setting is an environment variable, read by `backend/app/config.py`. This page lists all of them with their defaults, then the HTTP API.

**On this page:** [Settings](#where-settings-come-from) · [Model](#model) · [Agent](#agent) · [Server](#server) · [API routes](#api-routes) · [Streaming](#streaming) · [The response](#the-response) · [Login](#login) · [Headers and errors](#headers-and-errors)

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
| `OPENAI_MODEL` | (unset) | The model when `LLM_MODEL` is unset; the provider default is `gpt-4o-mini` |

### DeepSeek

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=<YOUR_API_KEY>
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-flash
LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}
```

`LLM_EXTRA_BODY` is required here. DeepSeek's V4 models think by default, and thinking mode rejects the forced tool choice the agent relies on (`400 Thinking mode does not support this tool_choice`). Blank does not mean non-thinking. Shapes differ between providers: NVIDIA NIM, for example, takes `{"chat_template_kwargs": {"thinking": true}}`.

How the model is chosen and what happens when a call fails: [architecture.md](architecture.md#models).

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

## API routes

While the backend runs, FastAPI's interactive docs are at http://localhost:8000/docs. Models are in `backend/app/schemas.py`.

| Method | Path | Does | Errors |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Status, version, active provider and model, whether `/api/connect` is allowed | None; never needs a login |
| `GET` | `/api/sample` | Loads the bundled sample into a new session | 500 if the sample file is missing |
| `POST` | `/api/upload` | Loads an uploaded `.csv` or `.tsv` (multipart field `file`) | 400 wrong type, unparseable or empty; 413 over `MAX_UPLOAD_MB` |
| `POST` | `/api/connect` | Connects a SQLAlchemy database URL | 403 when `ENABLE_DB_CONNECT` is off; 400 on any connection or table error |
| `GET` | `/api/dataset/{session_id}` | The schema and sample rows of a loaded session | 404 unknown or expired session |
| `POST` | `/api/query` | Runs the agent and returns the whole result | 404 unknown session |
| `POST` | `/api/query/stream` | Runs the agent and streams each step | 404 unknown session |

In the single deployment image, any other path serves the built frontend, so a hard refresh works; unknown paths under `/api/` still return 404.

## Loading data

```bash
curl -s http://localhost:8000/api/sample
curl -s -F "file=@orders.csv" http://localhost:8000/api/upload
curl -s http://localhost:8000/api/connect \
  -H "Content-Type: application/json" \
  -d '{"db_url": "postgresql+psycopg2://<USER>:<PASSWORD>@<HOST>/<DB>", "table": "orders"}'
```

`table` is optional; without it the first table is used. Postgres and MySQL need their driver installed (see `backend/requirements.txt`). All three return a `DatasetInfo`:

| Field | Type | Meaning |
| --- | --- | --- |
| `session_id` | string | Send this with every question |
| `table_name` | string | `data` for uploads and the sample |
| `row_count` | integer | Rows in the table |
| `columns` | list of `{name, dtype}` | The table's columns |
| `sample_rows` | list of objects | Up to five rows |
| `source` | string | `csv:<filename>` or `db:<dialect>` |

## Asking a question

`POST /api/query` and `POST /api/query/stream` take the same body:

```json
{
  "session_id": "<SESSION_ID>",
  "question": "What is total revenue by region?",
  "history": [{"question": "previous question", "answer": "previous answer"}]
}
```

`history` is optional; the last three turns are used.

## Streaming

![A question, end to end](images/question.svg)

`/api/query/stream` returns `text/event-stream`:

```
event: step
data: {"step": 1, "node": "decompose", "title": "Working as a single task", "detail": "...", "status": "ok", "payload": {}}

event: step
data: {"step": 2, "node": "plan", "branch": 0, "title": "Planned next step: sql", ...}

event: final
data: {"question": "...", "answer": "...", "branches": [...], ...}
```

| Event | When | Data |
| --- | --- | --- |
| `step` | Each time a node finishes, including inside parallel branches | One trace step |
| `final` | Once, at the end | The full response, as below |
| `error` | Only on an unexpected server bug | `{"message": "..."}`; details go to the server log |

A model outage or a lost session is not an `error` event: the run ends normally with a `final` event whose `error` field explains it. If the client disconnects, the run stops early ([architecture.md](architecture.md#stopping-early)).

A trace step has `step`, `node` (`decompose`, `plan`, `sql`, `python`, `chart`, `merge`, `verify`, `interpret`, `retry` or `error`), `branch` when it came from a branch, `title`, `detail`, `status` (`ok`, `retry` or `error`) and `payload`.

## The response

`/api/query` returns it directly; the stream sends it as the `final` event.

| Field | Meaning |
| --- | --- |
| `question`, `answer` | What was asked, and the written answer |
| `branches` | One entry per part: `branch_id`, `task`, `sql`, `python_code`, `python_result`, `chart_png_base64`, `chart_code`, `error` |
| `sql`, `python_code`, `python_result`, `chart_png_base64` | The first branch's of each, kept for clients written before branches existed |
| `verification` | `{verdict, notes, passes}` when the verifier ran |
| `trace` | Every step, in order |
| `steps` | Steps used |
| `error` | Set when the run couldn't finish, with a readable reason |

`sql` is `{sql, columns, rows, row_count, truncated}`; `truncated` is true when the result hit `MAX_SQL_ROWS`.

## Login

When `APP_USERNAME` and `APP_PASSWORD` are both set, every route except `/api/health` needs HTTP Basic credentials, and a request without them gets 401 with `WWW-Authenticate: Basic realm="Prism"`. Both halves are compared in constant time. The frontend is behind the same prompt.

## Headers and errors

Every response carries:

- `X-Request-ID`: an 8-character id that matches a line in the server log
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'`, `Referrer-Policy: same-origin`

An unhandled error returns `500` with `{"detail": "Internal server error.", "request_id": "<id>"}`, and the stack trace is logged under that id. Error details use FastAPI's usual `{"detail": "..."}` shape.

CORS allows `http://localhost:5173` and `http://127.0.0.1:5173` by default; change it with `CORS_ORIGINS`.
