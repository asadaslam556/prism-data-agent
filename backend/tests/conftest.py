"""Shared fixtures.

The LLM is mocked everywhere so the suite runs on any machine, CI included,
with no Ollama in sight. What's under test is everything around the model:
guardrails, the sandbox, data plumbing, the graph's control flow.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless backend before any pyplot import

import pandas as pd
import pytest

from app import config
from app.services import session as session_store


@pytest.fixture(autouse=True)
def shipped_defaults(monkeypatch):
    """Pin provider config to the values in config.py for every test.

    Two things leak in otherwise, and both cause failures that look like real
    bugs but aren't: whatever backend/.env happens to contain, and any
    ANTHROPIC_* / OPENAI_* variables set in the developer's shell (a PowerShell
    $PROFILE, say). The code deliberately reads those env vars at runtime, so
    tests asserting on defaults have to clear them or they're really asserting
    on whoever's machine they run on. Tests that care about a specific provider
    or model still set it themselves.
    """
    from app import config

    monkeypatch.setattr(config.settings, "llm_provider", "ollama")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.setattr(config.settings, "ollama_model", "qwen2.5")

    for name in (
        "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY",
        "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_API_KEY",
        "OLLAMA_MODEL", "OLLAMA_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_browser_login(monkeypatch):
    """Keep the login prompt out of the way of the API tests.

    _AUTH_ON is decided once at import time from settings or the environment,
    so a developer with APP_USERNAME set in their shell or their .env would
    otherwise watch every request in this suite come back 401. The auth logic
    itself is covered directly in test_server_ops.py.
    """
    from app import main

    monkeypatch.setattr(main, "_AUTH_ON", False)
    for name in ("APP_USERNAME", "APP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["North", "South", "North", "West"],
            "revenue": [100.0, 50.0, 25.0, 75.0],
            "quantity": [1, 2, 3, 4],
        }
    )


@pytest.fixture()
def sample_session(sample_df):
    return session_store.create_from_dataframe(sample_df, "data", "csv:test.csv")


@pytest.fixture()
def sales_session():
    """The bundled demo dataset, loaded exactly like the /api/sample endpoint."""
    return session_store.create_from_csv(
        str(config.settings.sample_data_path), config.settings.default_table_name, "csv:sales.csv"
    )


@pytest.fixture()
def mock_llm(monkeypatch):
    """Patch the LLM layer with deterministic canned responses.

    Handles all three structured calls the graph makes: the decomposer (one
    branch unless the question clearly names two things), each branch's planner
    (sql -> chart if wanted -> answer) and the verifier (always happy). Skills
    get syntactically valid SQL / pandas / matplotlib back.
    """
    from app.agent import graph as graph_module

    state = {"plan_calls": 0, "decompose_calls": 0, "verify_calls": 0}

    def fake_structured(system, user, schema):
        if schema is graph_module.Decomposition:
            state["decompose_calls"] += 1
            wants_chart = any(w in user.lower() for w in ("chart", "plot", "graph"))
            return graph_module.Decomposition(
                subtasks=[graph_module.SubTask(question=_root_question(user),
                                               needs_chart=wants_chart)],
                reasoning="single task",
            )
        if schema is graph_module.Verdict:
            state["verify_calls"] += 1
            return graph_module.Verdict(verdict="ok", notes="")

        state["plan_calls"] += 1
        if "SQL has run" not in user:
            return graph_module.NextStep(action="sql", reasoning="fetch data first")
        if "expected to produce a chart" in user:
            return graph_module.NextStep(action="chart", reasoning="visualise it")
        return graph_module.NextStep(action="answer", reasoning="done")

    def fake_complete(system, user):
        if "SQLite" in system:
            return (
                "```sql\nSELECT region, ROUND(SUM(revenue), 2) AS revenue "
                "FROM data GROUP BY region ORDER BY revenue DESC\n```"
            )
        if "visualisation" in system:
            return (
                "```python\ndf.plot(kind='bar', x='region', y='revenue', legend=False)\n"
                "plt.title('Revenue by region')\nplt.xlabel('Region')\nplt.ylabel('Revenue')\n```"
            )
        if "data scientist" in system:
            return "```python\nresult = df['revenue'].sum()\n```"
        return "North leads on revenue based on the query results."

    monkeypatch.setattr("app.agent.llm.structured", fake_structured)
    monkeypatch.setattr("app.agent.llm.complete", fake_complete)
    return state


def _root_question(user_prompt: str) -> str:
    """Pull the question back out of the decomposer prompt."""
    for line in user_prompt.splitlines():
        if line.startswith("USER QUESTION:"):
            return line.split(":", 1)[1].strip()
    return "the question"


@pytest.fixture()
def mock_llm_two_branches(monkeypatch, mock_llm):
    """Same as mock_llm but the decomposer always splits into two branches."""
    from app.agent import graph as graph_module

    original = graph_module.llm.structured

    def splitting(system, user, schema):
        if schema is graph_module.Decomposition:
            return graph_module.Decomposition(
                subtasks=[
                    graph_module.SubTask(question="Total revenue by region", needs_chart=False),
                    graph_module.SubTask(question="Total revenue by category", needs_chart=False),
                ],
                reasoning="two independent breakdowns",
            )
        return original(system, user, schema)

    monkeypatch.setattr("app.agent.llm.structured", splitting)
    return mock_llm