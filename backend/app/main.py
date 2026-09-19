"""FastAPI app.

Routes:
    GET  /api/health           liveness + which provider/model is active
    GET  /api/sample           load the bundled sample into a new session
    POST /api/upload           CSV/TSV upload -> new session
    POST /api/connect          external SQL database -> new session
    GET  /api/dataset/{id}     dataset metadata
    POST /api/query            run the agent, return everything at once
    POST /api/query/stream     run the agent, stream the trace over SSE

Every request gets a short id (X-Request-ID) and a timing log line. Unhandled
errors turn into a JSON 500 carrying that id, so a bug report with an id can
be matched to the stack trace in the server log.
"""
from __future__ import annotations

import base64
import io
import json
import secrets
import time
import uuid

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app import __version__, config
from app.agent import graph, providers
from app.hooks.logging_hook import logger
from app.schemas import (
    ColumnInfo,
    ConnectDBRequest,
    DatasetInfo,
    QueryRequest,
    QueryResponse,
)
from app.services import session as session_store

app = FastAPI(title="Prism", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    # Catching here (not in an exception handler) matters: handler responses
    # are built outside this middleware and would miss the header below.
    rid = uuid.uuid4().hex[:8]
    request.state.rid = rid
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception("unhandled error rid=%s: %s", rid, exc)
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "request_id": rid},
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = rid
    if request.url.path.startswith("/api"):
        logger.info(
            "%s %s -> %s (%.0f ms) rid=%s",
            request.method, request.url.path, response.status_code, elapsed_ms, rid,
        )
    return response


# --------------------------------------------------------- access control
# Set APP_USERNAME and APP_PASSWORD to put the whole app behind a browser login
# prompt. Both blank -- the default -- means no auth at all, which is what you
# want on a laptop. Set them on anything that has a public URL: this app has no
# other access control and your API key pays for every question asked.
# Read through settings, which covers both the real environment and
# backend/.env. os.environ alone misses the .env file, and the login used to
# be silently off because of it.
_AUTH_USER = config.settings.app_username.strip()
_AUTH_PASS = config.settings.app_password.strip()
_AUTH_ON = bool(_AUTH_USER and _AUTH_PASS)

# Hosting platforms ping this to decide whether the container is alive and
# can't send credentials, so it stays open. It leaks nothing but the model name.
_AUTH_EXEMPT = frozenset({"/api/health"})


def _credentials_ok(header: str | None) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return False
    user, _, password = decoded.partition(":")
    # Both halves compared every time. Short-circuiting on the username would
    # let an attacker learn it from how quickly the request comes back.
    user_ok = secrets.compare_digest(user, _AUTH_USER)
    pass_ok = secrets.compare_digest(password, _AUTH_PASS)
    return user_ok and pass_ok


@app.middleware("http")
async def require_login(request: Request, call_next):
    # Registered unconditionally and the switch checked per request, rather
    # than wrapping the registration in `if _AUTH_ON`. Middleware can't be
    # removed once the app object exists, so registering conditionally means a
    # stray APP_USERNAME in the environment turns every test into a 401 with
    # no way to switch it back off.
    if not _AUTH_ON or request.url.path in _AUTH_EXEMPT:
        return await call_next(request)
    if not _credentials_ok(request.headers.get("authorization")):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required."},
            headers={"WWW-Authenticate": 'Basic realm="Prism"'},
        )
    return await call_next(request)


def _dataset_info(session: session_store.DatasetSession) -> DatasetInfo:
    schema = session.schema
    return DatasetInfo(
        session_id=session.session_id,
        table_name=session.table_name,
        row_count=schema.row_count,
        columns=[ColumnInfo(name=n, dtype=d) for n, d in schema.columns],
        sample_rows=schema.sample_rows,
        source=session.source,
    )


def _format_history(history) -> str:
    if not history:
        return ""
    lines = ["PREVIOUS TURNS (for context):"]
    for turn in history[-3:]:
        lines.append(f"Q: {turn.question}\nA: {turn.answer}")
    return "\n".join(lines) + "\n\n"


def _require_session(session_id: str) -> None:
    try:
        session_store.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown session. Upload a dataset first.") from exc


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "provider": providers.active_provider(),
        "model": providers.active_model(),
    }


@app.get("/api/sample", response_model=DatasetInfo)
def load_sample() -> DatasetInfo:
    path = config.settings.sample_data_path
    if not path.exists():
        raise HTTPException(500, "Sample dataset not found.")
    session = session_store.create_from_csv(
        str(path), config.settings.default_table_name, "csv:sales.csv"
    )
    return _dataset_info(session)


@app.post("/api/upload", response_model=DatasetInfo)
async def upload(file: UploadFile = File(...)) -> DatasetInfo:  # noqa: B008 (FastAPI idiom)
    if not file.filename or not file.filename.lower().endswith((".csv", ".tsv")):
        raise HTTPException(400, "Please upload a .csv or .tsv file.")

    limit = config.settings.max_upload_mb * 1024 * 1024
    # One byte past the limit is enough to know it's too big, without pulling
    # a multi-gigabyte file into memory first.
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(
            413, f"File is too large. The limit is {config.settings.max_upload_mb} MB."
        )

    sep = "\t" if file.filename.lower().endswith(".tsv") else ","
    try:
        df = pd.read_csv(io.BytesIO(raw), sep=sep)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse the file: {exc}") from exc
    if df.empty:
        raise HTTPException(400, "The uploaded file has no rows.")

    session = session_store.create_from_dataframe(
        df, config.settings.default_table_name, f"csv:{file.filename}"
    )
    return _dataset_info(session)


@app.post("/api/connect", response_model=DatasetInfo)
def connect(request: ConnectDBRequest) -> DatasetInfo:
    # This endpoint dials whatever SQLAlchemy URL it is handed. That is a
    # reasonable thing to allow on your own machine and a bad thing to expose
    # to a network, so a deployment can switch it off (ENABLE_DB_CONNECT=false)
    # and keep sample + CSV upload.
    if not config.settings.enable_db_connect:
        raise HTTPException(403, "Database connections are disabled on this deployment.")
    try:
        session = session_store.create_from_url(request.db_url, request.table)
    except Exception as exc:
        raise HTTPException(400, f"Could not connect: {exc}") from exc
    return _dataset_info(session)


@app.get("/api/dataset/{session_id}", response_model=DatasetInfo)
def dataset(session_id: str) -> DatasetInfo:
    try:
        return _dataset_info(session_store.get(session_id))
    except KeyError as exc:
        raise HTTPException(404, "Unknown session. Upload a dataset first.") from exc


@app.post("/api/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    _require_session(request.session_id)
    state = graph.run(request.question, request.session_id, _format_history(request.history))
    return QueryResponse(**graph.to_response(state))


@app.post("/api/query/stream")
def query_stream(request: QueryRequest) -> StreamingResponse:
    _require_session(request.session_id)
    history = _format_history(request.history)

    def event_source():
        try:
            for event, data in graph.stream(request.question, request.session_id, history):
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
        except Exception as exc:
            # last resort -- graph.stream already downgrades provider outages
            # to a normal "final" event, so landing here means an actual bug
            logger.exception("stream failed: %s", exc)
            message = "The agent hit an unexpected error. The server log has the details."
            yield f"event: error\ndata: {json.dumps({'message': message})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


# --------------------------------------------------------------- frontend
# The Docker image builds the React app and drops it next to the package, so
# one container serves both and there is no CORS to configure. Running locally
# the folder isn't there -- Vite serves the app and proxies /api back here --
# and this whole block is skipped.
_DIST = config.settings.frontend_dist_path

if _DIST.is_dir():
    _DIST_ROOT = _DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """Serve a built asset, or index.html so a hard refresh still works."""
        # Registered after every real route, so anything still landing here
        # under /api is a genuine 404 rather than a page request.
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        if full_path:
            candidate = (_DIST_ROOT / full_path).resolve()
            # Resolve first, then confirm the result is still inside dist --
            # otherwise ../../etc/passwd walks straight out of it.
            if candidate.is_file() and _DIST_ROOT in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(_DIST_ROOT / "index.html")