"""Serialization regression tests.

Background: the SSE streaming endpoint serialises rows with ``json.dumps``. Raw
``DataFrame.to_dict()`` records can contain ``NaN`` (emitted as an invalid JSON
literal that browsers reject), ``numpy.int64`` (not serialisable at all) and
``pandas.Timestamp`` (ditto, from real databases). ``connectors.to_json_records``
sanitises rows at the source; these tests make sure that stays true.

Every JSON parse here is *browser-strict*: Python's ``json.loads`` accepts ``NaN``
by default, so a plain parse would hide exactly the bug being tested.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import sqlalchemy
from fastapi.testclient import TestClient

from app.agent import graph
from app.data import connectors
from app.main import app

client = TestClient(app)


def strict_json(text: str):
    """Parse like a browser: reject NaN/Infinity constants."""
    def refuse(constant):
        raise ValueError(f"invalid JSON constant: {constant}")
    return json.loads(text, parse_constant=refuse)


def stream_frames(session_id: str, question: str) -> list[tuple[str, dict]]:
    """Collect (event, strictly-parsed payload) pairs from the SSE endpoint."""
    with client.stream(
        "POST", "/api/query/stream", json={"session_id": session_id, "question": question}
    ) as response:
        raw = "".join(response.iter_text())
    frames = []
    for frame in raw.split("\n\n"):
        event, data = None, ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if event and data:
            frames.append((event, strict_json(data)))
    return frames


def _plan_sql_then_answer(monkeypatch, sql: str):
    monkeypatch.setattr(
        "app.agent.llm.structured",
        lambda s, u, sc: graph.NextStep(action="sql", reasoning="fetch")
        if "SQL has run" not in u
        else graph.NextStep(action="answer", reasoning="done"),
    )
    monkeypatch.setattr(
        "app.agent.llm.complete",
        lambda s, u: f"```sql\n{sql}\n```" if "SQLite" in s else "final answer",
    )


# ------------------------------------------------------------------- unit level

def test_to_json_records_handles_nan_numpy_and_timestamps():
    df = pd.DataFrame(
        {
            "count": np.array([1, 2], dtype=np.int64),
            "value": [1.5, np.nan],
            "when": [pd.Timestamp("2026-01-15 10:30"), pd.NaT],
        }
    )
    records = connectors.to_json_records(df)

    assert records[0]["count"] == 1 and type(records[0]["count"]) is int
    assert records[1]["value"] is None
    assert isinstance(records[0]["when"], str) and records[0]["when"].startswith("2026-01-15")
    assert records[1]["when"] is None
    json.dumps(records)  # must not raise


# -------------------------------------------------------------------- API level

def test_stream_with_null_values_is_browser_parseable(monkeypatch):
    # sales_rep contains genuine NULLs in the sample data
    _plan_sql_then_answer(
        monkeypatch, "SELECT sales_rep, revenue FROM data ORDER BY order_id LIMIT 100"
    )
    session_id = client.get("/api/sample").json()["session_id"]
    frames = stream_frames(session_id, "revenue by rep")

    final = dict(frames)["final"]
    reps = [row["sales_rep"] for row in final["sql"]["rows"]]
    assert None in reps, "expected NULLs to survive as JSON null"
    assert final["answer"]


def test_stream_with_integer_columns_is_browser_parseable(monkeypatch):
    _plan_sql_then_answer(
        monkeypatch, "SELECT region, COUNT(*) AS orders FROM data GROUP BY region"
    )
    session_id = client.get("/api/sample").json()["session_id"]
    frames = stream_frames(session_id, "orders per region")

    final = dict(frames)["final"]
    assert all(type(row["orders"]) is int for row in final["sql"]["rows"])
    assert final["sql"]["row_count"] == 4


def test_connect_file_sqlite_and_query_across_requests(monkeypatch, tmp_path):
    """/api/connect with a file database, then queries over separate requests.

    FastAPI serves sync endpoints from a threadpool, so this also exercises
    cross-thread use of the connected engine.
    """
    db_path = tmp_path / "external.db"
    engine = sqlalchemy.create_engine(f"sqlite:///{db_path}")
    pd.DataFrame({"city": ["Erlangen", "Nürnberg"], "population": [113000, 523000]}).to_sql(
        "data", engine, index=False
    )
    engine.dispose()

    _plan_sql_then_answer(monkeypatch, "SELECT city, population FROM data ORDER BY population DESC")

    response = client.post("/api/connect", json={"db_url": f"sqlite:///{db_path}"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    for _ in range(3):
        result = client.post(
            "/api/query", json={"session_id": session_id, "question": "biggest city?"}
        )
        assert result.status_code == 200
        body = result.json()
        assert body["error"] is None
        assert body["sql"]["rows"][0]["city"] == "Nürnberg"
