"""The agent: a graph of agent loops, not a single loop.

    START -> decompose --(fan out, in parallel)--> branch_1 ... branch_N -> merge
                  ^                                                          |
                  |                                                       verify
                  +------------------ retry, bounded ----------------------+ |
                                                                             v
                                                                        interpret -> END

Each branch is its own little agent running the classic loop in isolation:

    plan -> (sql | python | chart) -> back to plan -> ... -> done

So there are two levels. The worker level is the loop the project started with,
unchanged in spirit: one sub-question, one working DataFrame, plan and re-plan
until it has an answer, with a step cap so it always stops. The orchestrator
level is the new part -- it decides how many of those loops to run, runs them at
the same time, joins their results, and then hands the whole lot to a verifier
that can send everything back for another pass if the user asked for something
nobody actually fetched.

Two things fall out of that shape that a single loop can't give you. Independent
sub-questions get answered concurrently instead of one after another, which is
what you feel with a slow local model. And the verifier is a separate node
looking at the merged result, rather than the same planner that just did the
work grading its own homework.

Most questions still decompose to exactly one branch, and then this behaves
exactly like the old loop -- the extra machinery only shows up when the question
genuinely has independent parts.
"""
from __future__ import annotations

import queue
import re
import threading
from collections.abc import Iterator
from typing import Any, Literal

import pandas as pd
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from app import config
from app.agent import llm, prompts
from app.agent.providers import ProviderError
from app.agent.state import AgentState, BranchState
from app.data import connectors
from app.hooks import BudgetTracker, log_step
from app.services import session as session_store
from app.skills import chart_skill, interpret_skill, python_skill, sql_skill

Action = Literal["sql", "python", "chart", "answer"]
_CHART_WORDS = ("chart", "plot", "graph", "trend", "visual", "visualise", "visualize", "dashboard", "card", "kpi")


# ------------------------------------------------------------ structured outputs

class NextStep(BaseModel):
    """What one branch does next."""
    action: Action = Field(description="The single next action to take.")
    reasoning: str = Field(description="One short sentence explaining why.")


class SubTask(BaseModel):
    """One independently answerable piece of the user's question."""
    question: str = Field(description="A self-contained sub-question.")
    needs_chart: bool = Field(default=False, description="True if this part wants a visual.")


class Decomposition(BaseModel):
    """How the orchestrator wants to split the work."""
    subtasks: list[SubTask] = Field(description="Independent sub-questions, usually just one.")
    reasoning: str = Field(default="", description="One short sentence on the split.")


class Verdict(BaseModel):
    """The verifier's call on the gathered results."""
    verdict: Literal["ok", "retry"] = Field(description="ok = answer it, retry = something is missing.")
    notes: str = Field(default="", description="If retry, the one missing piece.")


# ------------------------------------------------------------------------ helpers

def _trace(step: int, node: str, title: str, detail: str = "", status: str = "ok",
           payload: dict | None = None, branch: int | None = None) -> dict:
    entry = {"step": step, "node": node, "title": title, "detail": detail,
             "status": status, "payload": payload or {}}
    if branch is not None:
        entry["branch"] = branch
    return entry


def _emit(sink: Any, entry: dict) -> list[dict]:
    """Record a step: push it to the live stream if someone's listening, and
    hand it back so it also lands in graph state for the final response."""
    if sink is not None:
        sink.put(entry)
    return [entry]


def _wants_chart(text: str) -> bool:
    return any(word in text.lower() for word in _CHART_WORDS)


def _branch_progress(state: BranchState) -> str:
    parts: list[str] = []
    if state.get("sql"):
        sql = state["sql"]
        preview = pd.DataFrame(sql["rows"][:5]).to_string(index=False) if sql["rows"] else "(no rows)"
        parts.append(f"- SQL has run ({sql['row_count']} rows). Preview:\n{preview}")
    if state.get("python_result"):
        parts.append(f"- Python analysis done:\n{state['python_result'][:600]}")
    if state.get("chart_png"):
        parts.append("- A chart has been produced.")
    if state.get("error"):
        parts.append(f"- Last error: {state['error']}")
    if state.get("wants_chart") and not state.get("chart_png"):
        # the decomposer flagged this branch as needing a visual; the planner
        # only ever sees the sub-question text, so spell it out
        parts.append("- This part is expected to produce a chart, which has not happened yet.")
    return "\n".join(parts) if parts else "- Nothing gathered yet."


def _branches_summary(state: AgentState) -> str:
    branches = state.get("branches") or []
    if not branches:
        return "- Nothing gathered yet."
    lines: list[str] = []
    for branch in sorted(branches, key=lambda b: b.get("branch_id", 0)):
        lines.append(f"[Sub-question] {branch.get('task', '')}")
        sql = branch.get("sql")
        if sql and sql.get("rows"):
            preview = pd.DataFrame(sql["rows"][:5]).to_string(index=False)
            lines.append(f"  Rows ({sql['row_count']}):\n{preview}")
        elif sql:
            lines.append("  Query returned no rows.")
        if branch.get("python_result"):
            lines.append(f"  Analysis: {branch['python_result'][:400]}")
        if branch.get("chart_png_base64"):
            lines.append("  A chart was produced for this part.")
        if branch.get("error"):
            lines.append(f"  Problem: {branch['error']}")
    return "\n".join(lines)


def _current_df(state: BranchState) -> pd.DataFrame:
    if isinstance(state.get("df"), pd.DataFrame) and not state["df"].empty:
        return state["df"]
    return session_store.get(state["session_id"]).dataframe()


# Words that describe the shape of a question rather than what it asks for.
# Stripping these leaves the part that decides whether two sub-questions are
# really the same. Aggregation words (total, average, count...) deliberately
# stay, because "total revenue" and "average revenue" are different questions.
_FILLER = {
    "what", "which", "is", "are", "was", "were", "the", "a", "an", "of", "for",
    "each", "every", "across", "full", "entire", "whole", "in", "on", "at", "by",
    "and", "or", "to", "me", "us", "show", "give", "list", "display", "all",
    "dataset", "data", "table", "per", "with", "from", "this", "that", "these",
    "how", "do", "does", "we", "i", "have", "has", "get", "find", "provide",
    "please", "chart", "charts", "graph", "plot", "visualise", "visualize",
    "as", "it", "its", "their", "there", "over", "within", "range", "period",
    "including", "include", "breakdown", "summary", "figures", "values", "value",
}


def _keywords(question: str) -> set[str]:
    words = re.findall(r"[a-z0-9_]+", question.lower())
    # crude singular form so "orders" and "order" count as the same word
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words} - _FILLER


def _same_question(left: set[str], right: set[str]) -> bool:
    """True when one sub-question is basically a reword of the other.

    Containment rather than Jaccard on purpose: models like to restate the same
    ask with extra qualifiers ("...across the full date range in the dataset"),
    which drags Jaccard down even though the questions are identical in intent.
    """
    if not left or not right:
        return False
    shared = len(left & right)
    return shared / min(len(left), len(right)) >= 0.8


def _drop_duplicates(tasks: list[dict], already_done: list[str] | None = None) -> list[dict]:
    """Keep the first of any group of sub-questions that ask the same thing.

    The prompt already tells the model not to overlap, and it mostly listens --
    but "mostly" means the occasional question gets planned, queried, charted
    and billed twice. Cheaper to check here than to hope.
    """
    kept: list[dict] = []
    # Seed with anything a previous pass already answered. Without this the
    # verifier retry re-decomposes, produces a reworded version of the same
    # sub-question, and the run ends up with two near-identical tasks and two
    # near-identical charts -- paid for twice.
    seen: list[set[str]] = [_keywords(q) for q in (already_done or [])]
    for task in tasks:
        words = _keywords(task["question"])
        if any(_same_question(words, other) for other in seen):
            log_step("decompose", f"dropped a duplicate sub-question: {task['question'][:60]}")
            continue
        seen.append(words)
        kept.append(task)
    return kept


def _heuristic_action(state: BranchState) -> Action:
    if not state.get("sql"):
        return "sql"
    if (state.get("wants_chart") or _wants_chart(state.get("task", ""))) and not state.get("chart_png"):
        return "chart"
    return "answer"


# ------------------------------------------------------------------ branch nodes

def plan_node(state: BranchState) -> dict:
    budget: BudgetTracker = state["budget"]
    step = budget.record_step()
    budget.record_llm_call()
    branch = state.get("branch_id", 0)

    if budget.exhausted:
        action: Action = "answer"
        reasoning = "Step budget reached; wrapping up with what this branch has."
    else:
        decision = llm.structured(
            prompts.PLANNER_SYSTEM,
            prompts.planner_user(state["task"], state["schema"], _branch_progress(state), ""),
            NextStep,
        )
        if isinstance(decision, NextStep):
            action, reasoning = decision.action, decision.reasoning
        else:
            # model couldn't give us structured output -- fall back to rules
            action = _heuristic_action(state)
            reasoning = "Planner fallback (heuristic routing)."

    log_step("plan", f"branch {branch} step {step}: -> {action} ({reasoning})")
    return {
        "next_action": action,
        "steps": step,
        "trace": _emit(state.get("sink"),
                       _trace(step, "plan", f"Planned next step: {action}", reasoning,
                              branch=branch)),
    }


def sql_node(state: BranchState) -> dict:
    step, branch = state["steps"], state.get("branch_id", 0)
    session = session_store.get(state["session_id"])
    result = sql_skill.run(session, state["task"])

    if not result.ok:
        return {"error": result.error,
                "trace": _emit(state.get("sink"),
                               _trace(step, "error", result.title, result.detail, "error",
                                      branch=branch))}

    df: pd.DataFrame = result.payload["dataframe"]
    sql_payload = {
        "sql": result.payload["sql"],
        "columns": result.payload["columns"],
        "rows": connectors.to_json_records(df),
        "row_count": result.payload["row_count"],
        "truncated": result.payload["truncated"],
    }
    return {
        "df": df,
        "sql": sql_payload,
        "error": "",
        "trace": _emit(state.get("sink"),
                       _trace(step, "sql", result.title, result.detail, "ok",
                              {"row_count": sql_payload["row_count"]}, branch=branch)),
    }


def python_node(state: BranchState) -> dict:
    step, branch = state["steps"], state.get("branch_id", 0)
    result = python_skill.run(_current_df(state), state["task"])
    ok = result.ok
    update: dict[str, Any] = {
        "trace": _emit(state.get("sink"),
                       _trace(step, "python" if ok else "retry", result.title, result.detail,
                              "ok" if ok else "retry",
                              {"result": result.payload.get("result", "")}, branch=branch))
    }
    if ok:
        update["python_code"] = result.payload["code"]
        update["python_result"] = result.payload["result"]
        # a previous attempt may have been rejected; it recovered, so the
        # branch is not in an error state any more
        update["error"] = ""
    else:
        # visible in the trace as a retry, but not carried on the branch --
        # the planner gets another go and usually gets it right
        update["last_attempt_error"] = result.error
    return update


def chart_node(state: BranchState) -> dict:
    step, branch = state["steps"], state.get("branch_id", 0)
    result = chart_skill.run(_current_df(state), state["task"])
    ok = result.ok
    update: dict[str, Any] = {
        "trace": _emit(state.get("sink"),
                       _trace(step, "chart" if ok else "retry", result.title, result.detail,
                              "ok" if ok else "retry", branch=branch))
    }
    if ok:
        update["chart_png"] = result.payload["png_base64"]
        update["chart_code"] = result.payload.get("code", "")
        update["error"] = ""
    else:
        update["last_attempt_error"] = result.error
    return update


def branch_route(state: BranchState) -> Literal["run_sql", "run_python", "make_chart", "done"]:
    return {
        "sql": "run_sql",
        "python": "run_python",
        "chart": "make_chart",
        "answer": "done",
    }.get(state.get("next_action", "answer"), "done")


def build_branch_graph():
    """The worker loop: one sub-question, plan and re-plan until it's done."""
    builder = StateGraph(BranchState)
    builder.add_node("plan", plan_node)
    builder.add_node("run_sql", sql_node)
    builder.add_node("run_python", python_node)
    builder.add_node("make_chart", chart_node)

    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan", branch_route,
        {"run_sql": "run_sql", "run_python": "run_python", "make_chart": "make_chart", "done": END},
    )
    # tools hand control back to the planner -- this is the re-analyse cycle
    builder.add_edge("run_sql", "plan")
    builder.add_edge("run_python", "plan")
    builder.add_edge("make_chart", "plan")
    return builder.compile()


_BRANCH_GRAPH = build_branch_graph()


# ------------------------------------------------------------ orchestrator nodes

def decompose_node(state: AgentState) -> dict:
    """Work out how many independent pieces this question really has."""
    budget: BudgetTracker = state["budget"]
    step = budget.record_step()
    budget.record_llm_call()

    feedback = state.get("verify_notes", "") if state.get("passes", 0) else ""
    plan = llm.structured(
        prompts.DECOMPOSE_SYSTEM,
        prompts.decompose_user(state["question"], state["schema"],
                               state.get("history", ""), feedback),
        Decomposition,
    )

    limit = max(1, config.settings.max_parallel_branches)
    if isinstance(plan, Decomposition) and plan.subtasks:
        done_already = [b.get("task", "") for b in (state.get("branches") or [])]
        tasks = _drop_duplicates(
            [{"question": t.question.strip(), "needs_chart": bool(t.needs_chart)}
             for t in plan.subtasks if t.question.strip()],
            already_done=done_already,
        )[:limit]
        reasoning = plan.reasoning or f"Split into {len(tasks)} part(s)."
    else:
        tasks = []
        reasoning = "Decomposer fallback: handling it as one question."

    if not tasks:
        if state.get("branches"):
            # A retry pass whose sub-questions were all duplicates of work
            # already done. Falling back to the whole question here would just
            # redo everything a third time; better to run nothing and let the
            # graph move on to the answer with what it already has.
            log_step("decompose", "retry produced only duplicates; nothing new to run")
            return {
                "subtasks": [],
                "dispatched": 0,
                "steps": step,
                "trace": _emit(state.get("sink"), _trace(
                    step, "decompose", "Nothing further to gather",
                    "The retry asked for work that was already done.")),
            }
        # every other failure path lands here: one branch, the whole question,
        # which is exactly how this worked before the graph grew branches
        tasks = [{"question": state["question"], "needs_chart": _wants_chart(state["question"])}]

    title = ("Working as a single task" if len(tasks) == 1
             else f"Split into {len(tasks)} parallel tasks")
    detail = reasoning if len(tasks) == 1 else "\n".join(
        f"{i + 1}. {t['question']}" for i, t in enumerate(tasks))
    log_step("decompose", f"{len(tasks)} branch(es)")
    return {
        "subtasks": tasks,
        "dispatched": len(tasks),
        "steps": step,
        "trace": _emit(state.get("sink"), _trace(step, "decompose", title, detail)),
    }


def fan_out(state: AgentState):
    """Hand each sub-question to its own worker. LangGraph runs these at once.

    Returning an empty list would make LangGraph skip merge and verify and
    walk straight off the end of the graph with no answer, so a pass with
    nothing left to run routes to merge by name instead.
    """
    tasks = state.get("subtasks") or []
    if not tasks:
        return "merge"

    offset = len(state.get("branches") or [])
    sends: list[Send] = []
    for index, task in enumerate(tasks):
        sends.append(Send("branch", {
            "branch_id": offset + index,
            "task": task["question"],
            "root_question": state["question"],
            "wants_chart": task.get("needs_chart", False),
            "session_id": state["session_id"],
            "schema": state["schema"],
            "budget": state["budget"],
            "sink": state.get("sink"),
            "steps": 0,
            "trace": [],
        }))
    return sends


def branch_node(state: BranchState) -> dict:
    """One parallel worker: runs the whole loop subgraph in its own context.

    Only a summary crosses back to the orchestrator. The DataFrame, the retry
    attempts and the half-finished state all stay in here.
    """
    branch = state.get("branch_id", 0)
    limit = config.settings.max_agent_steps * 4 + 5
    final = _BRANCH_GRAPH.invoke(state, config={"recursion_limit": limit})

    summary = {
        "branch_id": branch,
        "task": final.get("task", ""),
        "sql": final.get("sql"),
        "python_code": final.get("python_code"),
        "python_result": final.get("python_result"),
        "chart_png_base64": final.get("chart_png"),
        "chart_code": final.get("chart_code"),
        "error": final.get("error") or None,
    }
    # trace entries were pushed live as they happened; pass them on for state
    return {"branches": [summary], "trace": final.get("trace", [])}


def merge_node(state: AgentState) -> dict:
    """Fan-in. Nothing to compute -- the reducer already collected the branches."""
    budget: BudgetTracker = state["budget"]
    branches = state.get("branches") or []
    done = len(branches)
    failed = [b for b in branches if b.get("error")]
    step = budget.steps

    detail = f"{done} branch(es) finished"
    if failed:
        detail += f", {len(failed)} with problems"
    return {
        "steps": step,
        "trace": _emit(state.get("sink"),
                       _trace(step, "merge", "Merged branch results", detail,
                              "error" if failed and len(failed) == done else "ok")),
    }


def verify_node(state: AgentState) -> dict:
    """Second opinion: does what we gathered actually answer the question?"""
    budget: BudgetTracker = state["budget"]
    passes = state.get("passes", 0)
    branches = state.get("branches") or []

    # don't spend a model call when there's obviously nothing to check, or
    # when we've already used up our retries
    if not config.settings.enable_verifier or passes >= config.settings.max_verify_passes:
        return {"verdict": "ok", "trace": []}
    if budget.exhausted:
        return {"verdict": "ok",
                "trace": _emit(state.get("sink"),
                               _trace(budget.steps, "verify", "Skipped the check",
                                      "Step budget is spent; answering with what we have."))}

    step = budget.record_step()
    budget.record_llm_call()
    call = llm.structured(prompts.VERIFY_SYSTEM,
                          prompts.verify_user(state["question"], _branches_summary(state)),
                          Verdict)

    if isinstance(call, Verdict):
        verdict, notes = call.verdict, call.notes.strip()
    else:
        # a model that can't answer this cleanly shouldn't get to block the run
        verdict, notes = "ok", ""

    if verdict == "retry" and not branches:
        verdict = "ok"  # nothing to go back for

    title = "Results answer the question" if verdict == "ok" else "Found a gap, going back"
    log_step("verify", f"{verdict} {notes}".strip())
    return {
        "verdict": verdict,
        "verify_notes": notes,
        "passes": passes + 1,
        "steps": step,
        "trace": _emit(state.get("sink"),
                       _trace(step, "verify", title, notes, "ok" if verdict == "ok" else "error")),
    }


def route_after_verify(state: AgentState) -> Literal["decompose", "interpret"]:
    if state.get("verdict") == "retry" and state.get("passes", 0) <= config.settings.max_verify_passes:
        return "decompose"
    return "interpret"


def interpret_node(state: AgentState) -> dict:
    budget: BudgetTracker = state["budget"]
    step = budget.steps + 1
    result = interpret_skill.run(state["question"], _branches_summary(state))
    log_step("interpret", "final answer written")
    return {
        "answer": result.payload["answer"],
        "steps": step,
        "trace": _emit(state.get("sink"),
                       _trace(step, "interpret", "Wrote the answer", result.detail)),
    }


# --------------------------------------------------------------------- assembly

def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("decompose", decompose_node)
    builder.add_node("branch", branch_node)
    builder.add_node("merge", merge_node)
    builder.add_node("verify", verify_node)
    builder.add_node("interpret", interpret_node)

    builder.add_edge(START, "decompose")
    # one edge per sub-question, dispatched together
    builder.add_conditional_edges("decompose", fan_out, ["branch", "merge"])
    builder.add_edge("branch", "merge")
    builder.add_edge("merge", "verify")
    builder.add_conditional_edges("verify", route_after_verify, ["decompose", "interpret"])
    builder.add_edge("interpret", END)
    return builder.compile()


_GRAPH = build_graph()


# ------------------------------------------------------------------- entry points

def _initial_state(question: str, session_id: str, history: str, sink=None) -> AgentState:
    schema = session_store.get(session_id).schema.to_prompt()
    return {
        "question": question,
        "session_id": session_id,
        "schema": schema,
        "history": history,
        "steps": 0,
        "passes": 0,
        "branches": [],
        "budget": BudgetTracker(max_steps=config.settings.max_agent_steps),
        "sink": sink,
        "trace": [],
    }


def _recursion_limit() -> int:
    # room for: decompose -> branches -> merge -> verify, once per pass
    return (config.settings.max_verify_passes + 1) * 6 + config.settings.max_agent_steps + 10


_SESSION_GONE = (
    "That dataset is no longer loaded -- it either expired or was pushed out to make "
    "room for newer ones. Load it again and re-run the question."
)


def _failed_state(question: str, message: str) -> AgentState:
    # Something the agent can't work around -- the model backend is unreachable,
    # or the dataset went away underneath us. Hand back a state that renders as
    # a readable failure instead of a 500.
    log_step("error", message, status="error")
    return {
        "question": question,
        "answer": "",
        "error": message,
        "steps": 0,
        "branches": [],
        "trace": [_trace(0, "error", "Could not finish", message, "error")],
    }


def run(question: str, session_id: str, history: str = "") -> AgentState:
    """Run to completion and return the final state (sync API + tests)."""
    try:
        initial = _initial_state(question, session_id, history)
        return _GRAPH.invoke(initial, config={"recursion_limit": _recursion_limit()})
    except ProviderError as exc:
        return _failed_state(question, str(exc))
    except KeyError:
        # the session was evicted or expired between the API check and here
        return _failed_state(question, _SESSION_GONE)


_DONE = object()


def stream(question: str, session_id: str, history: str = "") -> Iterator[tuple[str, dict]]:
    """Yield ("step", ...) as each step finishes, then one ("final", ...).

    The graph runs on a background thread and nodes push their steps into a
    queue as they complete. That's what lets parallel branches report live and
    interleaved -- waiting for the parent state to settle would batch every
    branch's steps into one lump at the end.
    """
    sink: queue.Queue = queue.Queue()
    try:
        initial = _initial_state(question, session_id, history, sink=sink)
    except KeyError:
        yield "final", to_response(_failed_state(question, _SESSION_GONE))
        return
    outcome: dict[str, Any] = {}

    def drive():
        try:
            outcome["state"] = _GRAPH.invoke(initial, config={"recursion_limit": _recursion_limit()})
        except ProviderError as exc:
            outcome["failed"] = str(exc)
        except KeyError:
            outcome["failed"] = _SESSION_GONE
        except Exception as exc:  # noqa: BLE001 - re-raised on the consumer side
            outcome["crash"] = exc
        finally:
            sink.put(_DONE)

    worker = threading.Thread(target=drive, name="agent-graph", daemon=True)
    worker.start()

    while True:
        entry = sink.get()
        if entry is _DONE:
            break
        yield "step", entry

    worker.join()

    if "crash" in outcome:
        raise outcome["crash"]
    if "failed" in outcome:
        yield "final", to_response(_failed_state(question, outcome["failed"]))
        return
    yield "final", to_response(outcome.get("state", initial))


def to_response(state: AgentState) -> dict:
    """Shape the final state into the JSON the API returns.

    The single-result fields are kept alongside the branch list so anything
    written against the old shape still works: they point at the first branch
    that actually produced that kind of output.
    """
    branches = sorted(state.get("branches") or [], key=lambda b: b.get("branch_id", 0))

    def first(key: str):
        for branch in branches:
            if branch.get(key):
                return branch[key]
        return None

    verdict = state.get("verdict")
    verification = None
    if verdict:
        verification = {
            "verdict": verdict,
            "notes": state.get("verify_notes", ""),
            "passes": state.get("passes", 0),
        }

    return {
        "question": state.get("question", ""),
        "answer": state.get("answer", ""),
        "sql": first("sql"),
        "python_code": first("python_code"),
        "python_result": first("python_result"),
        "chart_png_base64": first("chart_png_base64"),
        "branches": branches,
        "verification": verification,
        "trace": state.get("trace", []),
        "steps": state.get("steps", 0),
        "error": state.get("error") or None,
    }
