"""Data layer tests: connectors, schema introspection, session registry."""
from __future__ import annotations

import pytest

from app import config
from app.data import connectors
from app.services import session as session_store


def test_dataframe_roundtrip(sample_df):
    engine = connectors.engine_from_dataframe(sample_df, "data")
    out = connectors.run_select(engine, "SELECT COUNT(*) AS n FROM data")
    assert int(out.iloc[0]["n"]) == len(sample_df)


def test_introspection_reports_schema(sample_df):
    engine = connectors.engine_from_dataframe(sample_df, "data")
    schema = connectors.introspect(engine, "data")
    names = [name for name, _ in schema.columns]
    assert names == ["region", "revenue", "quantity"]
    assert schema.row_count == 4
    assert len(schema.sample_rows) == 4
    prompt = schema.to_prompt()
    assert '"data"' in prompt and "region" in prompt


def test_introspection_unknown_table_raises(sample_df):
    engine = connectors.engine_from_dataframe(sample_df, "data")
    with pytest.raises(ValueError):
        connectors.introspect(engine, "nope")


def test_bundled_sample_dataset_loads():
    session = session_store.create_from_csv(
        str(config.settings.sample_data_path), "data", "csv:sales.csv"
    )
    assert session.schema.row_count == 1400
    names = [name for name, _ in session.schema.columns]
    assert {"order_date", "region", "category", "revenue"} <= set(names)


def test_session_store_registry(sample_df):
    session = session_store.create_from_dataframe(sample_df, "data", "csv:test.csv")
    fetched = session_store.get(session.session_id)
    assert fetched is session
    assert len(fetched.dataframe()) == 4
    with pytest.raises(KeyError):
        session_store.get("does-not-exist")
