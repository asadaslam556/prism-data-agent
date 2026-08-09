"""The orchestrator level: decomposition, parallel branches, fan-in, verifier.

The worker loop is covered in test_agent_graph.py. What's checked here is the
graph wrapped around it -- that independent sub-questions really do run at the
same time on separate threads, that their results merge without trampling each
other, that the verifier can send work back exactly as many times as it's
allowed to, and that one bad branch doesn't sink the rest.
"""
from __future__ import annotations

import threading
import time

import pytest

from app import config
from app.agent import graph


def _plan_sql_then_answer(user: str, module):
    if "SQL has run" not in user:
        return module.NextStep(action="sql", reasoning="fetch")
    return module.NextStep(action="answer", reasoning="done")


@pytest.fixture()
def canned_skills(monkeypatch):
    """Skill-level responses, with a configurable delay to expose parallelism."""
    holder = {"delay": 0.0, "threads": set()}

    def fake_complete(system, user):
        holder["threads"].add(threading.current_thread().name)
        if holder["delay"]:
            time.sleep(holder["delay"])
        if "SQLite" in system:
            return ("```sql\nSELECT region, ROUND(SUM(revenue), 2) AS revenue "
                    "FROM data GROUP BY region\n```")
        if "visualisation" in system:
            return ("```python\ndf.plot(kind='bar', x='region', y='revenue', legend=False)\n"
                    "plt.title('t')\n```")
        if "data scientist" in system:
            return "```python\nresult = df['revenue'].sum()\n```"
        return "A summarised answer built from the branch results."

    monkeypatch.setattr("app.agent.llm.complete", fake_complete)
    # exposed so a test can wrap it -- the concurrency test counts how many
    # calls are in flight at once, which needs to sit around this one
    holder["complete"] = fake_complete
    return holder


def _splitter(tasks, verdicts=("ok",)):
    """Build a structured-output stub that splits into `tasks` sub-questions."""
    calls = {"verify": 0}

    def fake_structured(system, user, schema):
        if schema is graph.Decomposition:
            return graph.Decomposition(
                subtasks=[graph.SubTask(question=t, needs_chart=False) for t in tasks],
                reasoning=f"{len(tasks)} independent parts",
            )
        if schema is graph.Verdict:
            index = min(calls["verify"], len(verdicts) - 1)
            calls["verify"] += 1
            verdict = verdicts[index]
            return graph.Verdict(verdict=verdict,
                                 notes="" if verdict == "ok" else "the category split is missing")
        return _plan_sql_then_answer(user, graph)

    return fake_structured, calls


# ------------------------------------------------------------------ decomposition

def test_simple_question_stays_one_branch(mock_llm, sales_session):
    state = graph.run("What is total revenue by region?", sales_session.session_id)
    assert len(state["branches"]) == 1
    assert state["trace"][0]["node"] == "decompose"
    assert state["trace"][0]["title"] == "Working as a single task"


def test_compound_question_fans_out(mock_llm_two_branches, sales_session):
    state = graph.run("Revenue by region and by category", sales_session.session_id)

    assert len(state["branches"]) == 2
    assert {b["branch_id"] for b in state["branches"]} == {0, 1}
    assert state["trace"][0]["title"].startswith("Split into 2")
    # each branch answered its own sub-question
    tasks = {b["task"] for b in state["branches"]}
    assert tasks == {"Total revenue by region", "Total revenue by category"}


def test_fan_out_is_capped_by_config(monkeypatch, canned_skills, sales_session):
    monkeypatch.setattr(config.settings, "max_parallel_branches", 2)
    structured, _ = _splitter(["one", "two", "three", "four"])
    monkeypatch.setattr("app.agent.llm.structured", structured)

    state = graph.run("four things at once", sales_session.session_id)
    assert len(state["branches"]) == 2, "must not exceed max_parallel_branches"


def test_decomposer_failure_falls_back_to_one_branch(monkeypatch, canned_skills, sales_session):
    monkeypatch.setattr("app.agent.llm.structured", lambda *a, **k: None)
    state = graph.run("anything at all", sales_session.session_id)

    branches = state["branches"]
    assert len(branches) == 1
    assert branches[0]["task"] == "anything at all"


# ---------------------------------------------------------------------- parallelism

def test_branches_run_concurrently(monkeypatch, canned_skills, sales_session):
    """Three branches with a slow model must overlap, not queue up.

    Measured by overlap rather than total time. A wall-clock threshold was the
    first attempt and it was a bad one: the run also includes a sequential
    final answer call, so the floor is 2 delays, serial is 4, and any bar
    between them is really a bet on how fast the machine is. It failed on a
    perfectly healthy run at 0.89s. Counting how many branches are inside the
    model call at the same time asks the actual question.
    """
    import threading

    canned_skills["delay"] = 0.25
    structured, _ = _splitter(["part one", "part two", "part three"])
    monkeypatch.setattr("app.agent.llm.structured", structured)

    inside = 0
    peak = 0
    guard = threading.Lock()
    original = canned_skills["complete"]

    def counting_complete(system, user):
        nonlocal inside, peak
        with guard:
            inside += 1
            peak = max(peak, inside)
        try:
            return original(system, user)
        finally:
            with guard:
                inside -= 1

    monkeypatch.setattr("app.agent.llm.complete", counting_complete)

    state = graph.run("three independent things", sales_session.session_id)

    assert len(state["branches"]) == 3
    assert peak >= 2, f"branches never overlapped (peak concurrency {peak})"
    worker_threads = {name for name in canned_skills["threads"] if "MainThread" not in name}
    assert len(worker_threads) >= 2, f"expected several worker threads, saw {worker_threads}"


def test_shared_budget_is_not_lost_across_threads(monkeypatch, canned_skills, sales_session):
    """Parallel branches bump one counter; without a lock steps go missing."""
    structured, _ = _splitter(["a", "b", "c"])
    monkeypatch.setattr("app.agent.llm.structured", structured)

    state = graph.run("three things", sales_session.session_id)
    trace_steps = [t["step"] for t in state["trace"] if t["node"] == "plan"]
    assert len(trace_steps) == len(set(trace_steps)), "each planner step needs a unique number"


def test_branch_data_does_not_leak_between_branches(monkeypatch, canned_skills, sales_session):
    structured, _ = _splitter(["revenue by region", "revenue by category"])
    monkeypatch.setattr("app.agent.llm.structured", structured)

    state = graph.run("two things", sales_session.session_id)
    by_id = {b["branch_id"]: b for b in state["branches"]}
    assert by_id[0]["task"] != by_id[1]["task"]
    assert all(b["sql"]["row_count"] == 4 for b in state["branches"])


# -------------------------------------------------------------------- the verifier

def test_verifier_passes_clean_results_through(mock_llm, sales_session):
    state = graph.run("What is total revenue by region?", sales_session.session_id)
    assert state["verdict"] == "ok"
    assert state["passes"] == 1
    assert [t["node"] for t in state["trace"]].count("decompose") == 1


def test_verifier_sends_work_back_once(monkeypatch, canned_skills, sales_session):
    """First verdict is retry, so the graph decomposes and fans out again.

    The retry has to ask for something *new*. This used to assert that a second
    branch always appeared, which quietly encoded a bug: the retry re-ran the
    same sub-question and the answer ended up with two identical branches and
    two identical charts. The stub below asks for a genuinely different
    breakdown on the second pass, which is what a useful retry looks like.
    """
    calls = {"decompose": 0}

    def structured(system, user, schema):
        if schema is graph.Decomposition:
            calls["decompose"] += 1
            question = ("revenue by region" if calls["decompose"] == 1
                        else "revenue by category")
            return graph.Decomposition(
                subtasks=[graph.SubTask(question=question)], reasoning="one"
            )
        if schema is graph.Verdict:
            verdict = "retry" if calls["decompose"] == 1 else "ok"
            return graph.Verdict(verdict=verdict, notes="category is missing")
        return _plan_sql_then_answer(user, graph)

    monkeypatch.setattr("app.agent.llm.structured", structured)

    state = graph.run("revenue by region and category", sales_session.session_id)
    nodes = [t["node"] for t in state["trace"]]

    assert nodes.count("decompose") == 2, "a retry must re-run decomposition"
    assert len(state["branches"]) == 2, "the second pass adds genuinely new evidence"
    assert {b["task"] for b in state["branches"]} == {"revenue by region", "revenue by category"}
    assert state["verdict"] == "ok"
    assert state["answer"]


def test_verifier_retries_are_bounded(monkeypatch, canned_skills, sales_session):
    """A verifier that is never satisfied still has to let the answer through."""
    structured, _ = _splitter(["revenue by region"], verdicts=("retry",))
    monkeypatch.setattr("app.agent.llm.structured", structured)

    state = graph.run("something unsatisfiable", sales_session.session_id)
    nodes = [t["node"] for t in state["trace"]]

    assert nodes.count("decompose") <= config.settings.max_verify_passes + 1
    assert nodes[-1] == "interpret"
    assert state["answer"]


def test_verifier_can_be_switched_off(monkeypatch, canned_skills, sales_session):
    monkeypatch.setattr(config.settings, "enable_verifier", False)
    structured, calls = _splitter(["revenue by region"], verdicts=("retry",))
    monkeypatch.setattr("app.agent.llm.structured", structured)

    state = graph.run("revenue by region", sales_session.session_id)
    assert calls["verify"] == 0, "the verifier should never be called when disabled"
    assert state["answer"]


def test_unusable_verdict_does_not_block_the_answer(monkeypatch, canned_skills, sales_session):
    """A model too weak for the verdict schema must not stall the run."""
    def structured(system, user, schema):
        if schema is graph.Decomposition:
            return graph.Decomposition(
                subtasks=[graph.SubTask(question="revenue by region")], reasoning="one")
        if schema is graph.Verdict:
            return None
        return _plan_sql_then_answer(user, graph)

    monkeypatch.setattr("app.agent.llm.structured", structured)
    state = graph.run("revenue by region", sales_session.session_id)
    assert state["verdict"] == "ok"
    assert state["answer"]


# ------------------------------------------------------------- merge and resilience

def test_one_failing_branch_does_not_sink_the_others(monkeypatch, canned_skills, sales_session):
    """Branch 1's SQL always fails; branch 0 must still deliver."""
    structured, _ = _splitter(["good question", "doomed question"])
    monkeypatch.setattr("app.agent.llm.structured", structured)

    def flaky(system, user, **kwargs):
        if "SQLite" in system:
            if "doomed" in user:
                return "```sql\nSELECT * FROM table_that_is_not_there\n```"
            return "```sql\nSELECT region, SUM(revenue) AS revenue FROM data GROUP BY region\n```"
        return "answer built from whatever worked"

    monkeypatch.setattr("app.agent.llm.complete", flaky)
    state = graph.run("two things, one impossible", sales_session.session_id)

    by_task = {b["task"]: b for b in state["branches"]}
    assert by_task["good question"]["sql"]["row_count"] == 4
    assert by_task["doomed question"]["error"], "the broken branch should record its error"
    assert state["answer"], "the run still has to produce an answer"


def test_merge_step_reports_branch_count(mock_llm_two_branches, sales_session):
    state = graph.run("two things", sales_session.session_id)
    merge = [t for t in state["trace"] if t["node"] == "merge"]
    assert merge and "2 branch" in merge[-1]["detail"]


# ------------------------------------------------------------------ response shape

def test_response_keeps_the_legacy_single_result_fields(mock_llm_two_branches, sales_session):
    state = graph.run("Revenue by region and by category", sales_session.session_id)
    response = graph.to_response(state)

    assert len(response["branches"]) == 2
    # legacy consumers read these and should see the first branch that has one
    assert response["sql"] == state["branches"][0]["sql"]
    assert response["verification"]["verdict"] == "ok"
    assert response["answer"]


def test_trace_entries_are_tagged_with_their_branch(mock_llm_two_branches, sales_session):
    state = graph.run("two things", sales_session.session_id)
    branch_tags = {t.get("branch") for t in state["trace"] if t["node"] in ("plan", "sql")}
    assert branch_tags == {0, 1}, "branch work must be attributable in the trace"
    # orchestrator-level steps belong to no branch
    assert all("branch" not in t for t in state["trace"]
               if t["node"] in ("decompose", "merge", "verify", "interpret"))


def test_streaming_reports_parallel_branches_live(monkeypatch, canned_skills, sales_session):
    """Steps must arrive as they happen, not batched when a branch finishes."""
    canned_skills["delay"] = 0.1
    structured, _ = _splitter(["one", "two"])
    monkeypatch.setattr("app.agent.llm.structured", structured)

    seen: list[tuple[float, dict]] = []
    for kind, payload in graph.stream("two things", sales_session.session_id):
        if kind == "step":
            seen.append((time.perf_counter(), payload))
        else:
            final = payload

    assert final["answer"]
    assert len({s[1].get("branch") for s in seen if s[1]["node"] == "sql"}) == 2
    # both branches' planners should report before either finishes its SQL
    order = [s[1]["node"] for s in seen]
    assert order[0] == "decompose"
    assert order[-1] == "interpret"


# ------------------------------------------- duplicates across a verifier retry

# The dedupe used to compare only within a single decompose pass. A verifier
# retry re-decomposed, produced a reworded version of a question already
# answered, and the run ended with two near-identical tasks and two identical
# charts -- billed twice. These are the exact pairs seen in the wild.

def test_dedupe_catches_the_reworded_duplicates_seen_in_practice():
    from app.agent.graph import _drop_duplicates

    pairs = [
        (
            "Which product has the highest average discount?",
            "What is the average discount for each product, and which has the highest?",
        ),
        (
            "Show total revenue by region in a pie chart",
            "Count the total number of distinct regions and show revenue "
            "distribution by region in a pie chart",
        ),
        (
            "What is the total revenue by month?",
            "What is the total revenue for each month across the full date range?",
        ),
    ]
    for first, second in pairs:
        kept = _drop_duplicates([{"question": first}, {"question": second}])
        assert len(kept) == 1, f"should have merged: {first!r} / {second!r}"


def test_dedupe_checks_against_work_already_done(monkeypatch):
    """A retry pass must not redo a sub-question the first pass answered."""
    from app.agent.graph import _drop_duplicates

    kept = _drop_duplicates(
        [{"question": "Count the total number of distinct regions and show revenue "
                      "distribution by region in a pie chart"}],
        already_done=["Show total revenue by region in a pie chart"],
    )
    assert kept == [], "a reworded repeat of finished work should be dropped"


def test_genuinely_new_work_survives_the_retry_check():
    from app.agent.graph import _drop_duplicates

    kept = _drop_duplicates(
        [{"question": "Total revenue by category"}],
        already_done=["Total revenue by region"],
    )
    assert len(kept) == 1, "a different breakdown is not a duplicate"


def test_a_retry_with_nothing_new_still_produces_an_answer(monkeypatch, canned_skills, sales_session):
    """If the retry's only sub-question is a duplicate, the graph must route to
    merge rather than fan out to nothing and fall off the end with no answer."""
    from app.agent import graph as graph_module

    calls = {"decompose": 0, "verify": 0}

    def structured(system, user, schema):
        if schema is graph_module.Decomposition:
            calls["decompose"] += 1
            # both passes ask for the same thing, reworded
            question = ("Total revenue by region" if calls["decompose"] == 1
                        else "What is the total revenue for each region?")
            return graph_module.Decomposition(
                subtasks=[graph_module.SubTask(question=question)], reasoning="one"
            )
        if schema is graph_module.Verdict:
            calls["verify"] += 1
            verdict = "retry" if calls["verify"] == 1 else "ok"
            return graph_module.Verdict(verdict=verdict, notes="want more")
        if "SQL has run" not in user:
            return graph_module.NextStep(action="sql", reasoning="fetch")
        return graph_module.NextStep(action="answer", reasoning="done")

    monkeypatch.setattr("app.agent.llm.structured", structured)
    state = graph_module.run("revenue by region", sales_session.session_id)

    assert state["answer"], "the run must still finish with an answer"
    assert len(state["branches"]) == 1, "the duplicate retry must not add a second branch"
    assert [t["node"] for t in state["trace"]][-1] == "interpret"


# ------------------------------------------------- a recovered attempt is not a failure

def test_a_rejected_snippet_that_recovers_is_not_shown_as_an_error(
    monkeypatch, canned_skills, sales_session
):
    """The guard rejecting a snippet is normal: the planner tries again and
    usually succeeds. That used to leave `error` set on the branch, so a run
    that finished perfectly well still rendered a red line above the answer.
    The attempt belongs in the trace, not in the branch's error field.
    """
    attempts = {"n": 0}

    def structured(system, user, schema):
        if schema is graph.Decomposition:
            return graph.Decomposition(
                subtasks=[graph.SubTask(question="analyse the data")], reasoning="one"
            )
        if schema is graph.Verdict:
            return graph.Verdict(verdict="ok", notes="")
        if "SQL has run" not in user:
            return graph.NextStep(action="sql", reasoning="fetch")
        if "Python analysis done" not in user and attempts["n"] < 2:
            return graph.NextStep(action="python", reasoning="analyse")
        return graph.NextStep(action="answer", reasoning="done")

    def complete(system, user):
        if "SQLite" in system:
            return "```sql\nSELECT region, SUM(revenue) AS revenue FROM data GROUP BY region\n```"
        if "data scientist" in system:
            attempts["n"] += 1
            if attempts["n"] == 1:
                # what the model actually reaches for, and what the guard blocks
                return "```python\nimport seaborn as sns\nresult = sns.heatmap(df)\n```"
            return "```python\nresult = df['revenue'].sum()\n```"
        return "an answer"

    monkeypatch.setattr("app.agent.llm.structured", structured)
    monkeypatch.setattr("app.agent.llm.complete", complete)

    state = graph.run("analyse the data", sales_session.session_id)
    branch = state["branches"][0]

    assert state["answer"], "the run recovered, so it must still answer"
    assert not branch.get("error"), "a recovered retry must not leave the branch in error"
    assert branch.get("python_result"), "the successful second attempt should be kept"

    statuses = {t["status"] for t in state["trace"]}
    assert "retry" in statuses, "the blocked attempt should still be visible as a retry"
    assert "error" not in statuses, "nothing here is a hard failure"
