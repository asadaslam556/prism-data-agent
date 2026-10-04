# Architecture

How Prism fits together, one diagram at a time. Each section says what the diagram shows and why it's built that way, then points to the page with the detail. Every image links to an interactive version you can open in a browser (see [Diagrams](README.md#diagrams)).

**On this page:** [System](#system) · [Agent](#agent) · [A question end to end](#a-question-end-to-end) · [Data](#data) · [Models](#models) · [Guardrails](#guardrails) · [Frontend](#frontend) · [Delivery](#delivery) · [Documentation map](#documentation-map) · [Testing approach](#testing-approach)

## System

### System overview

[![System overview](diagrams/system-overview.architecture.svg)](diagrams/system-overview.architecture.html)

One React app, one FastAPI process, one agent. Everything inside the dashed box runs in that single process: the API, the agent graph, the skills, the guardrails, the sandbox, the session registry, and the in-memory SQLite databases that hold uploaded CSVs. Only two things live outside it: the model provider, and your own database when you connect one.

The browser talks to the API over plain REST for loading data and over Server-Sent Events for a question, so steps appear while the agent works.

### Backend modules

[![Backend modules and their imports](diagrams/backend-modules.architecture.svg)](diagrams/backend-modules.architecture.html)

Arrows point from a module to what it imports, and nothing lower down imports back up. `main.py` knows the graph and the session registry; the graph drives the skills and asks the model layer for decisions; the skills use the guardrails, the sandbox and the connectors. Two things are left out to keep the picture readable: `config.py`, which most modules read, and a few extra imports listed in the diagram's notes.

## Agent

Details: [agent.md](agent.md).

### Orchestrator

[![Orchestrator graph](diagrams/orchestrator.architecture.svg)](diagrams/orchestrator.architecture.html)

The agent is two explicit LangGraph state graphs rather than a prebuilt agent helper, so the control flow is visible, testable and exactly what the UI shows. The orchestrator decides how many independent parts a question has (usually one), sends each to its own branch with LangGraph's `Send`, and runs them at the same time. `merge` is the join point; `verify` looks at the merged results and can send the work back to `decompose` at most `MAX_VERIFY_PASSES` times. If a retry produces only sub-questions that were already answered, `decompose` skips straight to `merge`.

### Branch loop

[![Branch worker loop](diagrams/branch-loop.architecture.svg)](diagrams/branch-loop.architecture.html)

Each branch runs the classic plan-act loop on its own state: `plan` picks one action, the tool runs, control comes back to `plan`, and `answer` ends the branch. The loop back is what lets a branch notice "the query is done, but a chart was asked for" and take another step.

### How plan decides

[![How plan picks the next action](diagrams/planner.architecture.svg)](diagrams/planner.architecture.html)

Small local models don't always manage structured output, so the planner degrades in stages. It records the step first; if the shared budget is spent, it answers with what it has. Otherwise it asks the model for a `NextStep`; if nothing usable comes back, a fixed rule decides (no SQL yet: query; chart owed: chart; otherwise: answer). An outage or a rejected request is different: that raises `ProviderError` and ends the run with a readable message.

### One question's lifecycle

[![Lifecycle of one question](diagrams/agent-run.lifecycle.svg)](diagrams/agent-run.lifecycle.html)

A run is started, decomposed, worked on by its branches, verified and answered. Two other endings exist: a model failure ends it with a readable error inside the final event, and a closed browser tab stops it early without writing an answer.

## A question end to end

[![A question, end to end](diagrams/question.sequence.svg)](diagrams/question.sequence.html)

The browser posts the question. FastAPI starts the graph on a background thread, and every node pushes its step into a queue the moment it finishes; the API relays each one as an SSE `step` event, then sends one `final` event with the full response. Because the queue is written as work happens, parallel branches report live and interleaved instead of in one lump when a branch ends.

[![Closing the tab stops the run](diagrams/disconnect.sequence.svg)](diagrams/disconnect.sequence.html)

If the browser goes away, a watcher in the API notices within half a second and sets a stop event. The step budget then reads as spent, so each branch answers at its next step, and the verifier and the final write-up skip their model calls. A model call already in flight still finishes; a thread can be told to stop but not killed.

## Data

Details: [data.md](data.md).

### Loading a dataset

[![Loading a dataset](diagrams/dataset-loading.sequence.svg)](diagrams/dataset-loading.sequence.html)

The sample and uploaded CSVs are written into a fresh in-memory SQLite database as a table called `data`; a database URL connects to your database instead. Either way the connector reads the schema, the row count and five sample rows, and the session registry stores the result under a new id.

### Session lifecycle

[![Dataset session lifecycle](diagrams/session.lifecycle.svg)](diagrams/session.lifecycle.html)

Sessions live in memory. Every request that uses one refreshes it. Two checks remove them: one older than `SESSION_TTL_MINUTES` is dropped on the next lookup or load, and past `MAX_SESSIONS` the least recently used goes. Both dispose of the engine so its connection is freed.

### Where the numbers come from

[![Where the numbers come from](diagrams/data-flow.dataflow.svg)](diagrams/data-flow.dataflow.html)

Every number in an answer comes from a query result. pandas and matplotlib work on that result, the response carries the rows, any analysis text and any chart, and the final answer is written from those computed values; the prompt tells the model to use only the numbers it was given and never invent figures. The browser redraws bar and line charts from the rows and shows the model's own PNG for other shapes.

### Locks for parallel branches

[![The four locks parallel branches need](diagrams/concurrency-locks.architecture.svg)](diagrams/concurrency-locks.architecture.html)

Running branches on real threads exposed four shared resources, each now behind one lock: the single shared SQLite connection, pyplot's global state, the step counter, and the session registry. The read lock only applies to in-memory engines, so real databases still read concurrently. [design-notes.md](design-notes.md) has the bug behind each one.

## Models

[![How Prism talks to a model](diagrams/model-providers.architecture.svg)](diagrams/model-providers.architecture.html)

Everything goes through `llm.py`, which offers `complete()` for text and `structured()` for a validated object and keeps one client per provider and model. `providers.py` is a small registry: `LLM_PROVIDER` picks the builder, and only that provider's SDK is imported. Details: [models.md](models.md).

## Guardrails

Details: [guardrails.md](guardrails.md) and [SECURITY.md](../SECURITY.md).

[![Layers around model-written Python](diagrams/python-sandbox.architecture.svg)](diagrams/python-sandbox.architecture.html)

Generated Python passes four layers: an AST check before anything runs, a namespace that hands out read-only module views and about twenty builtins, an audit hook that refuses file writes, processes and sockets at run time, and a watchdog that stops a snippet past `SANDBOX_TIMEOUT_SECONDS`. Each catches what the previous one can't see.

[![How a generated query gets run](diagrams/sql-guard.architecture.svg)](diagrams/sql-guard.architecture.html)

Generated SQL must be a single read-only statement and ends with a `LIMIT` no larger than `MAX_SQL_ROWS`. A rejected query or a database error goes back to the model with the message for another try.

## Frontend

[![Frontend components](diagrams/frontend.architecture.svg)](diagrams/frontend.architecture.html)

`App.jsx` owns the state and shows either the landing screen or the chat. `api.js` is the only file that talks to the backend; it reads the SSE stream from a `fetch` body because `EventSource` can't POST. Charts and markdown are drawn by hand, so the app has no runtime dependencies beyond React and never inserts model text as HTML. Details: [frontend.md](frontend.md).

## Delivery

Details: [deployment.md](deployment.md).

[![Three ways to run Prism](diagrams/deployment.architecture.svg)](diagrams/deployment.architecture.html)

Locally, Vite serves the app and proxies `/api` to uvicorn. `docker compose` runs the same split in three containers with Ollama. The root `Dockerfile` builds one image where FastAPI serves the built app and the API on one port, which is what runs on Render.

[![How a change lands](diagrams/ci.workflow.svg)](diagrams/ci.workflow.html)

Changes go through a pull request. CI lints and tests the backend on Python 3.11 and 3.12, builds the frontend and builds the deployment image; all four checks must pass before a squash merge, and Render redeploys `main`.

[![Running Prism on your machine](diagrams/local-setup.workflow.svg)](diagrams/local-setup.workflow.html)

[![Deploying to Render](diagrams/render-deploy.workflow.svg)](diagrams/render-deploy.workflow.html)

The setup and Render guides are [windows.md](windows.md), the [README quickstart](../README.md#quickstart) and [deploy-render.md](deploy-render.md).

## Documentation map

[![Where to find what](diagrams/docs-map.architecture.svg)](diagrams/docs-map.architecture.html)

The map at the top of [docs/README.md](README.md): one place to start, and the page for each kind of question.

## Testing approach

The model is mocked in every test. What's under test is everything around it: the guardrails, the sandbox, the data plumbing, and above all the control flow. Tools loop back to the planner, the fallback routes sensibly, the budget always ends the run, and streaming emits steps and then exactly one final event. Those properties hold whichever model is plugged in.
