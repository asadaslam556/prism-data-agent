"""The two state shapes the graph works with.

AgentState belongs to the orchestrator. BranchState belongs to one worker and
never leaves it -- each branch keeps its own question, its own DataFrame, its
own errors. That isolation is deliberate: when three branches run at once,
nothing one of them does can clobber another's working data. The only things
that cross back out are the finished branch summary and the trace entries.

Anything several branches write at the same time needs a reducer, otherwise
the parallel updates fight over the slot. `branches` and `trace` both append;
everything else is last-write-wins, which is what you want for a single
owner's field.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    # what came in
    question: str
    session_id: str
    schema: str
    history: str

    # orchestration
    subtasks: list[dict[str, Any]]   # decompose's plan for this pass
    dispatched: int                  # how many branches went out this pass
    passes: int                      # verifier round-trips used so far
    budget: Any                      # BudgetTracker, shared by every branch
    sink: Any                        # optional Queue for live streaming (see graph.stream)

    # fan-in (several branches write these concurrently)
    branches: Annotated[list[dict[str, Any]], operator.add]

    # verifier
    verdict: str                     # "ok" | "retry"
    verify_notes: str

    # what goes out
    answer: str
    error: str
    steps: int
    trace: Annotated[list[dict[str, Any]], operator.add]


class BranchState(TypedDict, total=False):
    """One worker's private world. Arrives via Send, dies when the branch ends."""
    branch_id: int
    task: str            # the sub-question this branch owns
    root_question: str   # the user's original wording, for context
    wants_chart: bool
    session_id: str
    schema: str
    budget: Any
    sink: Any

    next_action: str
    df: Any              # this branch's working DataFrame, never shared
    sql: dict[str, Any]
    python_code: str
    python_result: str
    chart_png: str
    chart_code: str
    error: str
    steps: int

    trace: Annotated[list[dict[str, Any]], operator.add]
