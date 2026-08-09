"""Pandas analysis for the things SQL can't say.

Works on the current DataFrame (usually the SQL result). Snippet gets the AST
check, then the sandbox.
"""
from __future__ import annotations

import pandas as pd

from app.agent import llm, prompts
from app.hooks import SafetyError, validate_python
from app.services import sandbox

from .base import SkillResult, describe_columns, extract_code

NAME = "python"
DESCRIPTION = "Run sandboxed pandas/numpy analysis on the query results."


def _stringify(value) -> str:
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return value.to_string()
    return str(value)


def run(df: pd.DataFrame, question: str) -> SkillResult:
    columns = describe_columns(df)
    raw = llm.complete(prompts.PYTHON_SYSTEM, prompts.python_user(question, columns))
    code = extract_code(raw, "python")

    try:
        validate_python(code)
    except SafetyError as exc:
        return SkillResult(ok=False, title="Analysis blocked", detail=str(exc), error=str(exc),
                           payload={"code": code})

    try:
        outcome = sandbox.run_analysis(code, df)
    except RuntimeError as exc:
        return SkillResult(ok=False, title="Analysis error", detail=str(exc), error=str(exc),
                           payload={"code": code})

    result_text = _stringify(outcome.result) if outcome.result is not None else outcome.stdout
    return SkillResult(
        ok=True,
        title="Analysed with pandas",
        detail=code,
        payload={"code": code, "result": result_text.strip()[:4000]},
    )
