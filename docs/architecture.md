# Architecture

This document explains how the agent works internally and why it is built the way it is. The README covers *what* it does; this covers *how* and the trade-offs behind it.

## Two graphs, not one

The agent is built from explicit LangGraph `StateGraph`s rather than a prebuilt ReAct helper. The extra code buys three things: the control flow is visible and testable, the routers are deterministic, and the trace the UI shows is the literal execution path, not a reconstruction.

**The worker graph** is the loop this project started with, scoped to a single sub-question:

```
START ──▶ plan ──▶ route ──┬──▶ run_sql ────┐
                           ├──▶ run_python ─┤   (each tool edge
                           ├──▶ make_chart ─┤    returns to plan)
                           └──▶ END          │
                                    ▲        │
                 plan ◀─────────────┴────────┘
```

On every visit `plan` looks at what this branch has gathered (SQL preview, python output, whether a chart exists, the last error) and picks exactly one next action via structured output. Tool nodes always come back, that edge is what lets a branch notice "the SQL result is enough, but a chart was asked for" and take another step, or see an error and route around it.

**The orchestrator graph** wraps several of those loops:

```
START ──▶ decompose ──┬──▶ branch ──┐
                      ├──▶ branch ──┼──▶ merge ──▶ verify ──┬──▶ interpret ──▶ END
                      └──▶ branch ──┘        ▲              │
                           ▲                 └── retry ─────┘
                           └─────────────────────┘
```

`decompose` decides how many independent sub-questions the request really contains, usually one. `fan_out` then emits one `Send` per sub-question, and LangGraph runs them concurrently on separate threads. `merge` is the join point; the reducer has already collected the branch summaries by the time it runs. `verify` is a second opinion on the merged result, and it can route back to `decompose` for a bounded number of passes.

Why split the levels at all? Two things fall out that a single loop can't give you. Independent sub-questions get answered concurrently instead of one after another, which is what you actually feel with a slow local model. And the verifier is a *separate* node grading the merged result, rather than the same planner that just did the work marking its own homework.

## Why branches keep their own state

Each worker runs on its own `BranchState`: its own sub-question, its own working DataFrame, its own errors. Nothing it does can reach another branch. Only a small summary crosses back out.

That isolation is what makes the parallelism safe. The alternative, one shared `df` field with last-write-wins, would have three branches silently overwriting each other's data mid-run. Anything several branches *do* write concurrently (`branches`, `trace`) carries an additive reducer instead, so the updates append rather than fight over the slot.

The step budget is deliberately the exception: one `BudgetTracker` is shared by every branch, so the cap is on total work rather than per branch. That means several threads increment the same counters, which is why it carries a lock, `self.steps += 1` is not atomic, and without it parallel branches quietly lose steps and overrun the budget.

## State design

`AgentState` is a `TypedDict`. Two decisions matter:

**The trace is additive.** `trace: Annotated[list[dict], operator.add]` gives the field a reducer, so each node returns just its own step and LangGraph appends it. Every other field is last-write-wins, which is exactly right for "the current DataFrame" or "the current error".

**The DataFrame stays in-process.** The working `pandas.DataFrame` is passed through state as a real object and never serialised mid-run; only the final response converts rows to JSON records. This keeps the python/chart skills fast and avoids type-lossy round-trips. The trade-off is that state can't be checkpointed to disk as-is, acceptable for a request-scoped agent, and the first thing to change if runs ever need to be resumable.

## What parallelism broke

Adding real threads surfaced a bug the sequential version could never hit, and it was the worst kind: silent.

The in-memory engines use `StaticPool`, one SQLite connection shared by every thread. That is exactly what makes an uploaded table visible across FastAPI's threadpool in the first place. But once branches started reading concurrently through that single connection, their cursors interleaved and handed each other's rows over. A stress test made it obvious: queries that must return 4, 4, 3 and 14 rows came back with 0, 5, 11 and 17, and a full-table fetch of a 1,400-row table returned 2,714 rows. No exception, no warning, just wrong numbers, in a tool whose entire job is producing correct numbers.

The fix is in `connectors.py`: reads on shared-connection engines are serialised behind a per-engine lock. Real databases (connection per thread) are untouched and still run genuinely concurrently. The cost is small because SQLite queries take milliseconds while the model calls they surround take seconds, the parallelism that matters is preserved.

## The planner's three safety nets

A local model's structured output can fail in ways a frontier API's rarely does. The planner degrades in order:

1. **Structured output**, `ChatOllama.with_structured_output(NextStep)` returns a validated Pydantic decision (`action` + one-sentence `reasoning`, which the trace shows).
2. **Heuristic fallback**, if that returns nothing usable, a deterministic rule routes: no SQL yet → `sql`; question mentions chart/plot/trend and no chart yet → `chart`; otherwise → `answer`. The trace marks these steps as fallbacks.
3. **The budget**, a `BudgetTracker` in the state counts planner visits. At `MAX_AGENT_STEPS` the action is forced to `answer`, so even a pathological loop ends with a best-effort explanation instead of a hang. The graph's `recursion_limit` is set above the budget so the budget, with its graceful ending, always fires first.

## Safety layering

Generated code passes through independent layers, so a bypass of one still hits the next:

| Layer | SQL | Python |
| --- | --- | --- |
| 1. Static validation | `sqlparse`: single statement, `SELECT`/`WITH` only, token-level keyword blocklist, auto-`LIMIT` | AST walk: no imports, no dunder attributes, no `eval`/`exec`/`open`/`getattr`/... |
| 2. Constrained execution | read-only usage of the engine; row cap | namespace with ~20 allow-listed builtins, copied `df`, captured stdout, headless matplotlib |
| 3. Failure containment | error fed back to the model for one retry, then a graceful failure step in the trace | `RuntimeError` surfaced to the agent, which can re-plan or answer without the analysis |

The keyword check is token-level on purpose: a substring check would reject legitimate columns like `discount` (contains `count`), a classic false positive this codebase tests against.

One production-shaped bug worth mentioning because the fix is easy to miss: an in-memory SQLite engine defaults to a per-thread connection pool, and FastAPI serves sync endpoints from a threadpool, so the thread handling `/api/query` would see an *empty* database. The engine therefore uses `StaticPool` with `check_same_thread=False`, sharing one connection across threads. The API test suite exercises exactly this path.

## Streaming

Streaming had to change when the graph gained branches. Reading the parent state after each node, the old approach, would batch every branch's steps into one lump the moment that branch finished, which is precisely the interesting part hidden.

So the graph now runs on a background thread and nodes push their trace entries into a queue as they complete; `stream()` drains that queue. The result is that parallel branches report live and interleaved, which is visible in a real run: two `plan` steps arrive back to back, then two `sql` steps, because both branches are genuinely working at once. Each entry carries the branch it came from, so the UI can lay them out in lanes.

The API layer then wraps each entry as an SSE `step` event, followed by one `final` event with the assembled response.

On the frontend, `EventSource` can't POST, so the client reads the `fetch` response body and parses SSE frames manually (`api.js`). The trace panel consumes the same step objects the backend logged, node name, title, detail, status, and derives the pipeline lights and the ×n visit badges from them. Nothing about the visualisation is invented client-side.

## The provider layer

`app/agent/providers.py` is a small registry: each provider is one builder
function tagged `@register("name")`, selected at runtime by `LLM_PROVIDER`.
`llm.py` exposes `complete()` and `structured()` on top and caches one client
per (provider, model) pair, so nothing else in the codebase knows which SDK is
underneath. Hosted-provider SDKs import lazily inside their builders -- the
default install stays Ollama-only, and picking an uninstalled provider tells
you the exact pip command.

Failures get sorted into two kinds. Transport and auth problems (connection
refused, 401, model not pulled) become a `ProviderError` with a message a
person can act on; `graph.run()`/`stream()` catch it and return a normal
response carrying that message, so an unreachable backend renders as a
readable answer in the UI rather than a 500. Anything else -- say a model that
can't produce structured output -- keeps its existing fallback behaviour.

## Skills and hooks

The split mirrors how these systems grow in practice:

- A **skill** is a vertical capability: prompt → generate → validate → execute → uniform `SkillResult`. Skills don't know about the graph; the graph's nodes are thin adapters around them, which is what makes them unit-testable with a mocked LLM.
- A **hook** is horizontal: safety, budget, logging. Hooks are imported by skills and nodes rather than woven into the graph, so reading any single skill shows its full guardrail story in one file.

## Testing philosophy

The LLM is mocked in every test. What's being verified is everything *around* the model, the guardrails, the sandbox, the data plumbing, and above all the control flow: that tools loop back to the planner, that the fallback routes sensibly, that the budget forcibly lands the plane, that streaming emits steps then exactly one final. Those properties hold regardless of which model is plugged in, which is the point: model quality changes answers, not the safety of the loop.
