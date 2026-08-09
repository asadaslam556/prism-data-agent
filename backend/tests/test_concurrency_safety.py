"""Things that only break once branches run at the same time.

Each of these covers a bug that actually happened during development, all of
them silent or hanging rather than loudly failing, and none of them reachable
from a single-branch run. They're slow-ish by test standards because faking the
concurrency wouldn't prove anything.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from app import config
from app.agent import graph
from app.data import connectors
from app.services import sandbox
from app.services import session as session_store

BAR = "df.plot(kind='bar', x='k', y='v', legend=False)\nplt.title('BARS')"
LINE = "df.plot(kind='line', x='k', y='v', legend=False)\nplt.title('LINE')"
DF_BAR = pd.DataFrame({"k": list("ABCD"), "v": [10, 20, 30, 40]})
DF_LINE = pd.DataFrame({"k": list("XY"), "v": [500, 900]})


def test_parallel_charts_do_not_deadlock_or_bleed():
    """pyplot is global state; two branches drawing at once used to hang.

    Also checks the figures don't mix: bars must stay bars and keep their own
    title, rather than picking up whatever the other thread was drawing.
    """
    def render(kind):
        code, frame = (BAR, DF_BAR) if kind == "bar" else (LINE, DF_LINE)
        out = sandbox.run_analysis(code, frame, with_plot=True)
        axes = out.result.get_axes()[0]
        return kind, axes.get_title(), len(axes.patches) + len(axes.lines), bool(out.figure_png)

    jobs = ["bar" if i % 2 == 0 else "line" for i in range(16)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(render, jobs))

    assert len(results) == 16, "a deadlock would never get here"
    for kind, title, artists, has_png in results:
        assert title == ("BARS" if kind == "bar" else "LINE")
        assert artists == (4 if kind == "bar" else 1)
        assert has_png


def test_runaway_snippet_is_stopped(monkeypatch):
    """No guardrail rejects `while True`, so the watchdog has to catch it."""
    monkeypatch.setattr(config.settings, "sandbox_timeout_seconds", 2)

    started = time.perf_counter()
    with pytest.raises(sandbox.SandboxTimeoutError):
        sandbox.run_analysis("while True:\n    pass", pd.DataFrame({"a": [1]}))
    elapsed = time.perf_counter() - started

    assert elapsed < 10, "the watchdog should fire near the limit, not eventually"


def test_watchdog_hands_tracing_back(monkeypatch):
    """settrace is global to the thread -- coverage and debuggers need it back."""
    import sys

    monkeypatch.setattr(config.settings, "sandbox_timeout_seconds", 5)
    before = sys.gettrace()
    sandbox.run_analysis("result = 1 + 1", pd.DataFrame({"a": [1]}))
    assert sys.gettrace() is before

    with pytest.raises(sandbox.SandboxTimeoutError):
        monkeypatch.setattr(config.settings, "sandbox_timeout_seconds", 1)
        sandbox.run_analysis("while True:\n    pass", pd.DataFrame({"a": [1]}))
    assert sys.gettrace() is before, "tracing must be restored even after a timeout"


def test_concurrent_reads_return_their_own_rows(sales_session):
    """One shared sqlite connection: interleaved cursors used to swap rows."""
    queries = {
        "SELECT region, SUM(revenue) r FROM data GROUP BY region": 4,
        "SELECT customer_segment, COUNT(*) c FROM data GROUP BY customer_segment": 3,
        "SELECT category, COUNT(*) c FROM data GROUP BY category": 4,
    }
    pairs = list(queries.items()) * 8

    def run(pair):
        sql, expected = pair
        return len(connectors.run_select(sales_session.engine, sql)), expected

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, pairs))

    assert all(got == expected for got, expected in results), \
        "a query returned another query's rows"


def test_full_table_fetches_stay_intact(sales_session):
    def fetch(_):
        return len(sales_session.dataframe())

    with ThreadPoolExecutor(max_workers=6) as pool:
        counts = set(pool.map(fetch, range(12)))

    assert counts == {1400}, f"parallel fetches disagreed on the row count: {counts}"


def test_shared_budget_counts_every_step():
    """Branches share one tracker; += 1 across threads used to drop steps."""
    from app.hooks import BudgetTracker

    budget = BudgetTracker(max_steps=10_000)
    seen: list[int] = []
    guard = threading.Lock()

    def bump():
        for _ in range(200):
            step = budget.record_step()
            with guard:
                seen.append(step)

    threads = [threading.Thread(target=bump) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert budget.steps == 1200
    assert len(set(seen)) == 1200, "two branches were handed the same step number"


# ------------------------------------------------------------ vanishing datasets

def test_query_on_an_evicted_session_reads_as_an_error(monkeypatch, sample_df, mock_llm):
    """Eviction mid-run used to escape as a bare KeyError, i.e. a 500."""
    victim = session_store.create_from_dataframe(sample_df, "data", "csv:victim.csv")
    monkeypatch.setattr(config.settings, "max_sessions", 2)
    for index in range(4):  # push the victim out
        session_store.create_from_dataframe(sample_df, "data", f"csv:filler{index}.csv")

    state = graph.run("anything", victim.session_id)
    assert state["error"] and "no longer loaded" in state["error"]
    assert state["trace"][-1]["status"] == "error"


def test_streaming_on_an_evicted_session_still_ends_cleanly(monkeypatch, sample_df, mock_llm):
    victim = session_store.create_from_dataframe(sample_df, "data", "csv:victim2.csv")
    monkeypatch.setattr(config.settings, "max_sessions", 2)
    for index in range(4):
        session_store.create_from_dataframe(sample_df, "data", f"csv:filler2{index}.csv")

    events = list(graph.stream("anything", victim.session_id))
    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "final"
    assert events[-1][1]["error"]
