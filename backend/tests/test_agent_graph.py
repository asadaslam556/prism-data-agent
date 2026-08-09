"""The worker loop: one branch planning, acting and re-planning.

These are the properties the loop has always had, now asserted against a
branch's result rather than a flat state: it fetches before answering, it
loops back to the planner after each tool, the heuristic fallback covers a
model that can't do structured output, and the budget always lands the plane.
"""
from __future__ import annotations

from app.agent import graph


def _only_branch(state):
    branches = state["branches"]
    assert len(branches) == 1, f"expected a single branch, got {len(branches)}"
    return branches[0]


def test_sql_only_flow(mock_llm, sales_session):
    state = graph.run("What is total revenue by region?", sales_session.session_id)
    branch = _only_branch(state)

    assert state["answer"]
    assert branch["sql"]["row_count"] == 4  # four regions in the sample data
    assert branch["chart_png_base64"] is None

    nodes = [t["node"] for t in state["trace"]]
    assert nodes[0] == "decompose"
    assert "sql" in nodes and nodes[-1] == "interpret"
    assert "chart" not in nodes


def test_chart_flow_produces_png_and_loops_back(mock_llm, sales_session):
    state = graph.run("Show revenue by region as a chart", sales_session.session_id)
    branch = _only_branch(state)

    assert branch["chart_png_base64"], "expected a base64 PNG"

    nodes = [t["node"] for t in state["trace"]]
    first_sql = nodes.index("sql")
    # the re-analyse cycle: the planner runs again after the tool
    assert "plan" in nodes[first_sql + 1:], "tool nodes must return to the planner"
    assert nodes[-1] == "interpret"


def test_streaming_emits_steps_then_final(mock_llm, sales_session):
    events = list(graph.stream("Total revenue by region", sales_session.session_id))
    kinds = [kind for kind, _ in events]

    assert kinds[-1] == "final"
    assert kinds.count("final") == 1
    assert all(kind == "step" for kind in kinds[:-1])

    final = events[-1][1]
    assert final["answer"] and final["sql"]["rows"]


def test_heuristic_fallback_when_structured_output_fails(monkeypatch, mock_llm, sales_session):
    # a model that can't produce structured output at all: no decomposition,
    # no verdict, no planner decisions -- everything falls back to rules
    monkeypatch.setattr("app.agent.llm.structured", lambda *a, **k: None)

    state = graph.run("What is total revenue by region?", sales_session.session_id)
    branch = _only_branch(state)

    assert state["answer"]
    assert branch["sql"]["row_count"] == 4
    assert branch["task"] == "What is total revenue by region?"


def test_heuristic_fallback_still_charts_when_asked(monkeypatch, mock_llm, sales_session):
    monkeypatch.setattr("app.agent.llm.structured", lambda *a, **k: None)
    state = graph.run("Show revenue by region as a chart", sales_session.session_id)
    assert _only_branch(state)["chart_png_base64"]


def test_budget_stops_a_looping_planner(monkeypatch, mock_llm, sales_session):
    """A planner that always wants more SQL must still land on an answer."""
    from app.agent import graph as graph_module

    def greedy(system, user, schema):
        if schema is graph_module.Decomposition:
            return graph_module.Decomposition(
                subtasks=[graph_module.SubTask(question="revenue by region")],
                reasoning="one task",
            )
        if schema is graph_module.Verdict:
            return graph_module.Verdict(verdict="ok", notes="")
        return graph_module.NextStep(action="sql", reasoning="more data!")

    monkeypatch.setattr("app.agent.llm.structured", greedy)
    state = graph.run("What is total revenue by region?", sales_session.session_id)

    from app.config import settings
    assert state["budget"].steps >= settings.max_agent_steps
    assert state["answer"], "the agent must still answer when the budget runs out"
    assert state["trace"][-1]["node"] == "interpret"
