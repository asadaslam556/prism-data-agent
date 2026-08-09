"""Bits shared by all skills.

A skill is one capability (sql, python, chart, interpret) in one module, all
returning the same SkillResult shape. New capability = new file + a line in
the registry + a mention in the planner prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def extract_code(text: str, language: str) -> str:
    """First fenced code block from a model reply.

    Small models forget the fence now and then, so the fallback is the whole
    reply with stray backticks stripped.
    """
    pattern = rf"```(?:{language})?\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.replace("```", "").strip()


def describe_columns(df) -> str:
    """Column names with their types, e.g. "region (text), revenue (number)".

    Passing bare names left the model guessing which columns it could do
    arithmetic on, and it guessed wrong -- calling .mean() on a text column
    fails with a TypeError that costs a retry. Types are cheap to send.
    """
    import pandas as pd

    parts = []
    for name in df.columns:
        dtype = df[name].dtype
        # bool has to be checked before numeric -- pandas counts it as
        # numeric, and calling .mean() on flags is rarely what was meant
        if pd.api.types.is_bool_dtype(dtype):
            kind = "boolean"
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            kind = "date"
        elif pd.api.types.is_numeric_dtype(dtype):
            kind = "number"
        else:
            kind = "text"
        parts.append(f"{name} ({kind})")
    return ", ".join(parts)


@dataclass
class SkillResult:
    """Uniform result returned by every skill."""
    ok: bool
    title: str
    detail: str = ""
    payload: dict = field(default_factory=dict)
    error: str | None = None
