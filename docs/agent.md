# The agent

How a question becomes an answer: the two graphs in `backend/app/agent/graph.py`, the state they share, how the planner decides, and how steps reach the browser. [architecture.md](architecture.md) has the overview.

**On this page:** [Two graphs](#two-graphs) · [Decompose](#decompose) · [Branches](#branches) · [The planner](#the-planner) · [Verify and interpret](#verify-and-interpret) · [State](#state) · [The step budget](#the-step-budget) · [Streaming](#streaming) · [Stopping early](#stopping-early) · [Endings](#endings) · [Trace steps](#trace-steps)

## Two graphs

[![Orchestrator graph](diagrams/orchestrator.architecture.svg)](diagrams/orchestrator.architecture.html)

The orchestrator (`build_graph`) runs `decompose → branch × N → merge → verify → interpret`. Each `branch` node runs the worker graph (`build_branch_graph`) on its own state. Both are explicit LangGraph `StateGraph`s: the routing is deterministic, the steps the UI shows are the real execution path, and every edge is covered by a test with the model mocked.

## Decompose

`decompose_node` asks the model for a `Decomposition`: a list of `SubTask`s, each a self-contained sub-question with a `needs_chart` flag. Most questions come back as one sub-question; the prompt only allows a split when the parts are genuinely independent.

The code then:

- **Drops near-duplicates.** Two sub-questions count as the same when, after removing filler words, at least 80% of the shorter one's keywords appear in the other (`_same_question`). On a verifier retry, sub-questions already answered count too, so a reworded repeat isn't run and paid for twice.
- **Caps the count** at `MAX_PARALLEL_BRANCHES` (default 3).
- **Falls back** to the whole question as one task if the model's output isn't usable, flagging a chart when the question contains words like *chart*, *plot*, *trend* or *kpi*.

If a retry leaves nothing new to run, `fan_out` routes straight to `merge` instead of returning an empty list, which would otherwise end the graph with no answer.

## Branches

[![Branch worker loop](diagrams/branch-loop.architecture.svg)](diagrams/branch-loop.architecture.html)

`fan_out` sends one `Send("branch", …)` per sub-question and LangGraph runs them at the same time. Inside a branch:

| Node | Does |
| --- | --- |
| `plan` | Picks the single next action: `sql`, `python`, `chart` or `answer` |
| `run_sql` | The SQL skill: write a query, validate it, run it, retry with the error ([guardrails.md](guardrails.md)) |
| `run_python` | The pandas skill: write a snippet, check it, run it in the sandbox |
| `make_chart` | The chart skill: write matplotlib code, check it, run it, return a PNG |

Every tool hands control back to `plan`; `answer` ends the branch, and only a summary (task, SQL result, analysis, chart, error) goes back to the orchestrator.

## The planner

[![How plan picks the next action](diagrams/planner.architecture.svg)](diagrams/planner.architecture.html)

`plan_node` records a step first, then:

1. If the shared budget is spent, the action is `answer`.
2. Otherwise it asks for a `NextStep` (an action plus one sentence of reasoning, which the UI shows) through `llm.structured()`, which always uses function calling. DeepSeek rejects the JSON-schema response format LangChain would otherwise pick, so function calling is used everywhere.
3. If the model returns nothing usable, `_heuristic_action` decides: no SQL yet → `sql`; a chart is owed and none exists → `chart`; otherwise → `answer`.

The planner sees what its branch has so far: a preview of the SQL result, any pandas output, whether a chart exists, the last error, and a note when the decomposer flagged the part as needing a chart.

## Verify and interpret

`verify_node` asks the model whether the merged results answer the question (`Verdict`: `ok` or `retry` plus a note). It returns `ok` without a model call when `ENABLE_VERIFIER` is off, when `MAX_VERIFY_PASSES` retries are used up (default 1), or when the budget is spent. A `retry` goes back to `decompose` with the note as feedback.

`interpret_node` writes the answer from a summary of every branch's results. The prompt tells the model to use only those numbers, describe the whole result, and never invent figures or claim a chart type that wasn't drawn.

## State

| State | Owner | Notes |
| --- | --- | --- |
| `AgentState` | Orchestrator | Question, schema, history, sub-tasks, the shared budget, the step queue, merged `branches`, verdict, answer, `trace` |
| `BranchState` | One branch | Its sub-question, its own DataFrame, SQL result, analysis, chart, last error, its `trace` |

Each branch works on its own `BranchState`, so nothing it does can reach another branch. The two fields several branches write at once, `branches` and `trace`, use an additive reducer (`Annotated[list, operator.add]`), so parallel updates append instead of overwriting each other. The DataFrame travels through state as a live object and is only turned into JSON for the response.

## The step budget

One `BudgetTracker` is shared by every branch, so `MAX_AGENT_STEPS` (default 16) caps the total work for a question, not each branch. Several threads update it, so it's locked. LangGraph's own recursion limit is set above the budget (`(MAX_VERIFY_PASSES + 1) × 6 + MAX_AGENT_STEPS + 10` for the orchestrator, `MAX_AGENT_STEPS × 4 + 5` per branch), so the budget's graceful "answer now" always comes first.

## Streaming

[![A question, end to end](diagrams/question.sequence.svg)](diagrams/question.sequence.html)

`graph.stream()` runs the graph on a background thread named `agent-graph`. Each node pushes its trace entry into a queue the moment it finishes; `stream()` yields them as `("step", entry)` and ends with one `("final", response)`. The API wraps those as SSE events ([api.md](api.md#streaming)). Reading the graph's state after each node would batch a branch's steps until it finished; the queue is what makes parallel branches appear live and interleaved.

`graph.run()` does the same without streaming, for `POST /api/query` and the tests.

## Stopping early

[![Closing the tab stops the run](diagrams/disconnect.sequence.svg)](diagrams/disconnect.sequence.html)

`POST /api/query/stream` creates a stop event and passes it to `graph.stream()`. A watcher polls `request.is_disconnected()` every 0.5 seconds and sets the event when the client leaves; the stream also sets it if it's closed before the end. A set stop event makes the budget read as spent, so each branch answers at its next step, the verifier skips its check, and `interpret` returns without a model call.

## Endings

[![Lifecycle of one question](diagrams/agent-run.lifecycle.svg)](diagrams/agent-run.lifecycle.html)

| Ending | Cause | What the client gets |
| --- | --- | --- |
| Answered | The normal path | `event: final` with the answer, results and trace |
| Failed | A `ProviderError` from any model call, or the dataset session disappearing | `event: final` whose `error` field says what to check |
| Stopped | The client disconnected | Nothing; nobody is listening |
| Crashed | An unexpected bug | `event: error` with a generic message; details go to the server log |

## Trace steps

Every step the UI shows is a trace entry: `step`, `node`, `branch` (when it came from a branch), `title`, `detail`, `status` and `payload`.

| `node` | Emitted by |
| --- | --- |
| `decompose`, `plan`, `merge`, `verify`, `interpret` | The node of the same name |
| `sql`, `python`, `chart` | A tool that succeeded |
| `retry` | A pandas or chart snippet that was rejected or failed |
| `error` | A failed SQL step, or a run that couldn't finish |

`status` is `ok`, `retry` or `error`. The verifier marks "found a gap, going back" as `error` so it stands out, even though a retry is a normal outcome.
