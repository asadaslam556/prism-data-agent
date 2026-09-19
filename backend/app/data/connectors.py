"""Engines, introspection, and row shaping.

Every dataset ends up behind a SQLAlchemy engine -- uploaded CSVs go into an
in-memory SQLite, external databases connect by URL -- so the SQL skill never
has to care where the data came from.
"""
from __future__ import annotations

import json
import threading
import weakref
from contextlib import contextmanager
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Engine, create_engine, func, inspect, literal_column, select, table, text
from sqlalchemy.pool import StaticPool


def to_json_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows as strictly JSON-safe records.

    Goes through pandas' own JSON encoder: NaN/NaT -> null, numpy scalars ->
    plain ints/floats, datetimes -> ISO strings. The streaming endpoint dumps
    rows with json.dumps, which chokes on numpy types and emits a bare NaN
    that browsers refuse to parse -- learned that one the hard way.
    """
    return json.loads(df.to_json(orient="records", date_format="iso"))


@dataclass
class Schema:
    table_name: str
    columns: list[tuple[str, str]]  # (name, dtype)
    sample_rows: list[dict]
    row_count: int

    def to_prompt(self, max_sample: int = 5) -> str:
        """Compact text version of the schema for prompts."""
        cols = "\n".join(f"  - {name} ({dtype})" for name, dtype in self.columns)
        sample = pd.DataFrame(self.sample_rows[:max_sample]).to_string(index=False)
        return (
            f'Table "{self.table_name}" ({self.row_count} rows)\n'
            f"Columns:\n{cols}\n\n"
            f"Sample rows:\n{sample}"
        )


def engine_from_csv(csv_path: str, table_name: str) -> Engine:
    """CSV -> fresh in-memory SQLite engine."""
    df = pd.read_csv(csv_path)
    return engine_from_dataframe(df, table_name)


def engine_from_dataframe(df: pd.DataFrame, table_name: str) -> Engine:
    # StaticPool = one connection shared by every thread. Without it each
    # FastAPI worker thread gets its own empty in-memory db and the table
    # you just loaded is nowhere to be found.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    df.to_sql(table_name, engine, index=False, if_exists="replace")
    return engine


def engine_from_url(db_url: str) -> Engine:
    return create_engine(db_url)


def introspect(engine: Engine, table_name: str | None) -> Schema:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if not tables:
        raise ValueError("No tables found in the connected database.")
    if table_name is None:
        table_name = tables[0]
    elif table_name not in tables:
        raise ValueError(f"Table '{table_name}' not found. Available: {', '.join(tables)}")

    columns = [(c["name"], str(c["type"])) for c in inspector.get_columns(table_name)]

    source = table(table_name)
    with _read_guard(engine), engine.connect() as conn:
        row_count = conn.execute(select(func.count()).select_from(source)).scalar_one()
        sample = pd.read_sql(select(literal_column("*")).select_from(source).limit(5), conn)

    return Schema(
        table_name=table_name,
        columns=columns,
        sample_rows=to_json_records(sample),
        row_count=int(row_count),
    )


# --- keeping concurrent reads honest -----------------------------------------
# The in-memory engines use StaticPool, i.e. ONE sqlite connection shared by
# every thread. That's what makes the uploaded table visible across FastAPI's
# threadpool at all -- but once the agent started running branches in parallel
# it bit back: two threads reading through the same connection interleave and
# quietly hand each other's rows over. No exception, just wrong numbers, which
# is the last thing you want in an analysis tool. So reads on those engines get
# serialised. Real databases (QueuePool, connection per thread) are untouched
# and still run genuinely concurrently.
_ENGINE_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_LOCK_REGISTRY_GUARD = threading.Lock()


def _shares_one_connection(engine: Engine) -> bool:
    return isinstance(engine.pool, StaticPool)


def _lock_for(engine: Engine) -> threading.RLock:
    with _LOCK_REGISTRY_GUARD:
        lock = _ENGINE_LOCKS.get(engine)
        if lock is None:
            lock = threading.RLock()
            _ENGINE_LOCKS[engine] = lock
        return lock


@contextmanager
def _read_guard(engine: Engine):
    if _shares_one_connection(engine):
        with _lock_for(engine):
            yield
    else:
        yield


def read_table(engine: Engine, table_name: str) -> pd.DataFrame:
    """A whole table as a DataFrame, with the name quoted by the dialect."""
    with _read_guard(engine), engine.connect() as conn:
        return pd.read_sql(select(literal_column("*")).select_from(table(table_name)), conn)


def run_select(engine: Engine, sql: str) -> pd.DataFrame:
    """Run an (already validated) read-only query."""
    with _read_guard(engine), engine.connect() as conn:
        return pd.read_sql(text(sql), conn)
