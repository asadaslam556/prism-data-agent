"""In-memory registry of loaded datasets.

Each upload / connect / sample-load becomes a DatasetSession keyed by a short
random id. Sessions live in the process, so a restart clears them -- fine for
a single-user tool. Two things keep memory honest on a long-running server:
a cap on how many sessions we hold (oldest gets evicted, LRU-style) and a TTL
so abandoned sessions don't hang around with an open engine.

Swap this module for Redis or a DB if you ever need multi-process.
"""
from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import Engine

from app.config import settings
from app.data import connectors
from app.hooks.logging_hook import logger


@dataclass
class DatasetSession:
    session_id: str
    engine: Engine
    table_name: str
    schema: connectors.Schema
    source: str
    last_used: float = field(default_factory=time.monotonic)

    def dataframe(self) -> pd.DataFrame:
        """Full table as a DataFrame (what the python/chart skills work on)."""
        return connectors.run_select(self.engine, f'SELECT * FROM "{self.table_name}"')


_SESSIONS: OrderedDict[str, DatasetSession] = OrderedDict()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _drop(session_id: str, reason: str) -> None:
    session = _SESSIONS.pop(session_id, None)
    if session is None:
        return
    # Free the sqlite connection / db pool right away instead of waiting on GC.
    try:
        session.engine.dispose()
    except Exception:
        pass
    logger.info("session %s dropped (%s)", session_id, reason)


def _evict_if_needed() -> None:
    while len(_SESSIONS) > settings.max_sessions:
        oldest = next(iter(_SESSIONS))
        _drop(oldest, "evicted, session cap reached")


def create_from_csv(csv_path: str, table_name: str, source: str) -> DatasetSession:
    engine = connectors.engine_from_csv(csv_path, table_name)
    schema = connectors.introspect(engine, table_name)
    return _register(engine, schema, source)


def create_from_dataframe(df: pd.DataFrame, table_name: str, source: str) -> DatasetSession:
    engine = connectors.engine_from_dataframe(df, table_name)
    schema = connectors.introspect(engine, table_name)
    return _register(engine, schema, source)


def create_from_url(db_url: str, table: str | None) -> DatasetSession:
    engine = connectors.engine_from_url(db_url)
    schema = connectors.introspect(engine, table)
    return _register(engine, schema, f"db:{engine.dialect.name}")


def _register(engine: Engine, schema: connectors.Schema, source: str) -> DatasetSession:
    session = DatasetSession(
        session_id=_new_id(),
        engine=engine,
        table_name=schema.table_name,
        schema=schema,
        source=source,
    )
    _SESSIONS[session.session_id] = session
    _evict_if_needed()
    return session


def get(session_id: str) -> DatasetSession:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise KeyError(session_id)

    ttl = settings.session_ttl_minutes * 60
    if time.monotonic() - session.last_used > ttl:
        _drop(session_id, "expired")
        raise KeyError(session_id)

    session.last_used = time.monotonic()
    _SESSIONS.move_to_end(session_id)
    return session
