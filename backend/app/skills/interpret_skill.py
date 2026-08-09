"""Writes the final answer from the gathered results.

The prompt is strict about only using supplied numbers -- without that, models
happily invent figures nobody computed.
"""
from __future__ import annotations

from app.agent import llm, prompts

from .base import SkillResult

NAME = "interpret"
DESCRIPTION = "Summarise the gathered results into a final answer."


def run(question: str, results: str) -> SkillResult:
    answer = llm.complete(prompts.INTERPRET_SYSTEM, prompts.interpret_user(question, results))
    return SkillResult(ok=True, title="Wrote the answer", detail=answer.strip(),
                       payload={"answer": answer.strip()})
