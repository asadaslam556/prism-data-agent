"""HTTP layer tests via FastAPI's TestClient (no server, no Ollama needed)."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sample_dataset_endpoint():
    response = client.get("/api/sample")
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 1400
    assert any(col["name"] == "revenue" for col in body["columns"])
    assert body["session_id"]


def test_upload_csv():
    csv_bytes = b"region,revenue\nNorth,100\nSouth,50\n"
    response = client.post(
        "/api/upload",
        files={"file": ("mini.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 2
    assert body["source"] == "csv:mini.csv"

    # metadata endpoint agrees
    meta = client.get(f"/api/dataset/{body['session_id']}")
    assert meta.status_code == 200
    assert meta.json()["row_count"] == 2


def test_upload_rejects_non_csv():
    response = client.post(
        "/api/upload",
        files={"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
    )
    assert response.status_code == 400


def test_query_unknown_session_is_404():
    response = client.post("/api/query", json={"session_id": "nope", "question": "hi"})
    assert response.status_code == 404


def test_query_end_to_end(mock_llm):
    session_id = client.get("/api/sample").json()["session_id"]
    response = client.post(
        "/api/query",
        json={"session_id": session_id, "question": "Total revenue by region?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["sql"]["row_count"] == 4          # legacy single-result field
    assert body["branches"][0]["sql"]["row_count"] == 4
    assert body["verification"]["verdict"] == "ok"
    assert body["trace"][0]["node"] == "decompose"


def test_query_stream_emits_sse(mock_llm):
    session_id = client.get("/api/sample").json()["session_id"]
    with client.stream(
        "POST",
        "/api/query/stream",
        json={"session_id": session_id, "question": "Total revenue by region?"},
    ) as response:
        assert response.status_code == 200
        payload = "".join(response.iter_text())
    assert "event: step" in payload
    assert "event: final" in payload
