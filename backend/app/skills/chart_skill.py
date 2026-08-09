"""Matplotlib chart -> base64 PNG.

Shipping a PNG means the browser needs zero plotting libraries. The generated
code runs through the same validation + sandbox as everything else, headless.
"""
from __future__ import annotations

import pandas as pd

from app.agent import llm, prompts
from app.hooks import SafetyError, validate_python
from app.services import sandbox

from .base import SkillResult, describe_columns, extract_code

NAME = "chart"
DESCRIPTION = "Create a matplotlib visualisation of the results."


def run(df: pd.DataFrame, question: str) -> SkillResult:
    columns = describe_columns(df)
    raw = llm.complete(prompts.CHART_SYSTEM, prompts.chart_user(question, columns))
    code = extract_code(raw, "python")

    try:
        validate_python(code)
    except SafetyError as exc:
        return SkillResult(ok=False, title="Chart blocked", detail=str(exc), error=str(exc),
                           payload={"code": code})

    try:
        outcome = sandbox.run_analysis(code, df, with_plot=True)
    except RuntimeError as exc:
        return SkillResult(ok=False, title="Chart error", detail=str(exc), error=str(exc),
                           payload={"code": code})

    png = outcome.figure_png
    if not png:
        return SkillResult(ok=False, title="Chart error", detail="No figure was produced.",
                           error="empty figure", payload={"code": code})

    return SkillResult(
        ok=True,
        title="Rendered a chart",
        detail=code,
        payload={"code": code, "png_base64": png},
    )
