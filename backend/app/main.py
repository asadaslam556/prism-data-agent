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

import io
import json
import time
import uuid

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

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

app = FastAPI(title="AI Data Analyst Agent", version=__version__)

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

    raw = await file.read()
    limit = config.settings.max_upload_mb * 1024 * 1024
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
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
