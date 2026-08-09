"""Skill registry.

New capability: drop a module here exposing NAME / DESCRIPTION / run(), add it
to CAPABILITIES, mention it in the planner prompt. That's the whole process.
"""
from . import chart_skill, interpret_skill, python_skill, sql_skill
from .base import SkillResult

CAPABILITIES = {
    sql_skill.NAME: sql_skill.DESCRIPTION,
    python_skill.NAME: python_skill.DESCRIPTION,
    chart_skill.NAME: chart_skill.DESCRIPTION,
    interpret_skill.NAME: interpret_skill.DESCRIPTION,
}

__all__ = [
    "sql_skill",
    "python_skill",
    "chart_skill",
    "interpret_skill",
    "SkillResult",
    "CAPABILITIES",
]
