"""The ops layer: limits, eviction, request ids, the 500 handler, health."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import session as session_store

client = TestClient(app)


def test_health_reports_provider_and_version():
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["provider"] == "ollama"
    assert body["model"] and body["version"]


def test_responses_carry_a_request_id():
    response = client.get("/api/health")
    assert len(response.headers["X-Request-ID"]) == 8


def test_upload_over_the_size_limit_is_rejected(monkeypatch):
    monkeypatch.setattr(config.settings, "max_upload_mb", 0)
    response = client.post(
        "/api/upload",
        files={"file": ("big.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
    )
    assert response.status_code == 413
    assert "limit" in response.json()["detail"].lower()


def test_unhandled_errors_become_json_500s(monkeypatch):
    crashing = TestClient(app, raise_server_exceptions=False)
    monkeypatch.setattr("app.main.graph.run", lambda *a, **k: 1 / 0)
    session_id = crashing.get("/api/sample").json()["session_id"]
    response = crashing.post(
        "/api/query", json={"session_id": session_id, "question": "boom"}
    )
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error."
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_session_cap_evicts_the_oldest(monkeypatch, sample_df):
    monkeypatch.setattr(config.settings, "max_sessions", 3)
    made = [
        session_store.create_from_dataframe(sample_df, "data", f"csv:{i}.csv")
        for i in range(5)
    ]
    for old in made[:2]:
        with pytest.raises(KeyError):
            session_store.get(old.session_id)
    for kept in made[2:]:
        assert session_store.get(kept.session_id) is kept


def test_sessions_expire_after_the_ttl(monkeypatch, sample_df):
    monkeypatch.setattr(config.settings, "session_ttl_minutes", 1)
    session = session_store.create_from_dataframe(sample_df, "data", "csv:ttl.csv")
    session.last_used -= 120  # pretend two minutes went by
    with pytest.raises(KeyError):
        session_store.get(session.session_id)


def test_touching_a_session_keeps_it_alive(monkeypatch, sample_df):
    monkeypatch.setattr(config.settings, "max_sessions", 2)
    a = session_store.create_from_dataframe(sample_df, "data", "csv:a.csv")
    b = session_store.create_from_dataframe(sample_df, "data", "csv:b.csv")
    session_store.get(a.session_id)  # a is now most recently used
    session_store.create_from_dataframe(sample_df, "data", "csv:c.csv")
    with pytest.raises(KeyError):
        session_store.get(b.session_id)  # b was the stale one
    assert session_store.get(a.session_id) is a


def test_provider_outage_reaches_the_client_as_a_normal_response(monkeypatch):
    from app.agent.providers import ProviderError

    def down(*_args, **_kwargs):
        raise ProviderError("Could not get a response from ollama (qwen2.5).")

    monkeypatch.setattr("app.agent.llm.structured", down)
    monkeypatch.setattr("app.agent.llm.complete", down)

    session_id = client.get("/api/sample").json()["session_id"]
    response = client.post(
        "/api/query", json={"session_id": session_id, "question": "hi"}
    )
    assert response.status_code == 200  # not a 500 -- it's an expected condition
    body = response.json()
    assert body["error"] and "ollama" in body["error"]
