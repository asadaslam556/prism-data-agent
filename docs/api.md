# API reference

The backend is a FastAPI app (`backend/app/main.py`). While it runs, FastAPI's interactive docs are at http://localhost:8000/docs. Models are in `backend/app/schemas.py`.

**On this page:** [Routes](#routes) · [Loading data](#loading-data) · [Asking a question](#asking-a-question) · [Streaming](#streaming) · [The response](#the-response) · [Login](#login) · [Headers and errors](#headers-and-errors)

## Routes

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

A model outage or a lost session is not an `error` event: the run ends normally with a `final` event whose `error` field explains it. If the client disconnects, the run stops early ([agent.md](agent.md#stopping-early)).

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

CORS allows `http://localhost:5173` and `http://127.0.0.1:5173` by default; change it with `CORS_ORIGINS` ([configuration.md](configuration.md)).
