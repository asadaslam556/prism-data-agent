"""Question -> SQL -> validate -> run, with retries.

Local models flub SQL more often than API models, so the loop here earns its
keep: every query goes through the guardrail, and a failed execution gets fed
back to the model (error message and all) for a bounded retry before we give
up politely.
"""
from __future__ import annotations

import pandas as pd

from app import config
from app.agent import llm, prompts
from app.data import connectors
from app.hooks import SafetyError, validate_sql
from app.services.session import DatasetSession

from .base import SkillResult, extract_code

NAME = "sql"
DESCRIPTION = "Run a read-only SQL SELECT against the dataset."


def run(session: DatasetSession, question: str) -> SkillResult:
    schema = session.schema.to_prompt()
    max_rows = config.settings.max_sql_rows
    attempts = config.settings.sql_retry_attempts + 1

    error: str | None = None
    for attempt in range(attempts):
        raw = llm.complete(prompts.SQL_SYSTEM, prompts.sql_user(question, schema, error))
        sql = extract_code(raw, "sql")
        try:
            safe_sql = validate_sql(sql, max_rows)
        except SafetyError as exc:
            error = str(exc)
            continue

        try:
            df = connectors.run_select(session.engine, safe_sql)
        except Exception as exc:  # execution error -> retry with the message
            error = f"{type(exc).__name__}: {exc}"
            continue

        truncated = len(df) >= max_rows
        return SkillResult(
            ok=True,
            title="Queried the data",
            detail=safe_sql,
            payload={
                "sql": safe_sql,
                "dataframe": df,
                "columns": list(df.columns),
                "row_count": int(len(df)),
                "truncated": truncated,
                "attempt": attempt + 1,
            },
        )

    return SkillResult(
        ok=False,
        title="SQL failed",
        detail=error or "Unknown error",
        error=error,
        payload={"dataframe": pd.DataFrame()},
    )
