"""Pydantic models shared across the API layer."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    name: str
    dtype: str


class DatasetInfo(BaseModel):
    session_id: str
    table_name: str
    row_count: int
    columns: list[ColumnInfo]
    sample_rows: list[dict[str, Any]]
    source: str  # "csv:<filename>" or "db:<dialect>"


class ConnectDBRequest(BaseModel):
    db_url: str = Field(..., description="SQLAlchemy connection URL, e.g. postgresql+psycopg2://...")
    table: str | None = Field(None, description="Table to analyse. Defaults to the first table found.")


class HistoryTurn(BaseModel):
    question: str
    answer: str


class QueryRequest(BaseModel):
    session_id: str
    question: str
    history: list[HistoryTurn] = Field(default_factory=list)


class TraceStep(BaseModel):
    """A single step the agent took, surfaced live to the UI."""
    step: int
    node: Literal["decompose", "plan", "sql", "python", "chart",
                  "merge", "verify", "interpret", "retry", "error"]
    branch: int | None = None
    title: str
    detail: str = ""
    status: Literal["running", "ok", "retry", "error"] = "ok"
    payload: dict[str, Any] = Field(default_factory=dict)


class SQLResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False


class BranchResult(BaseModel):
    """What one parallel worker came back with."""
    branch_id: int
    task: str
    sql: SQLResult | None = None
    python_code: str | None = None
    python_result: str | None = None
    chart_png_base64: str | None = None
    chart_code: str | None = None
    error: str | None = None


class Verification(BaseModel):
    """The verifier's call on the merged results."""
    verdict: Literal["ok", "retry"]
    notes: str = ""
    passes: int = 0


class QueryResponse(BaseModel):
    question: str
    answer: str
    # These four describe the first branch that produced each kind of output.
    # Kept so anything built against the pre-branch shape still works.
    sql: SQLResult | None = None
    python_code: str | None = None
    python_result: str | None = None
    chart_png_base64: str | None = None
    branches: list[BranchResult] = Field(default_factory=list)
    verification: Verification | None = None
    trace: list[TraceStep]
    steps: int
    error: str | None = None
