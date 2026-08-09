# Project Guide, Prism

This is the complete walkthrough of the project: what every part is, how a question flows through the system, how to run it from scratch, how it was verified, and where to take it next. If you read only one file, read this one.

---

## 1. What this project is

A full-stack, fully local "AI data analyst". You bring data (CSV upload, SQL database, or the bundled sample), ask a question in plain English, and an **agent**, not a single prompt, figures out how to answer it: it plans steps, writes SQL, runs pandas, draws charts, checks its own progress, and explains the result. A live trace panel in the UI shows every step as it happens.

Everything runs on your machine: the LLM (via Ollama), the database, the code sandbox. No API keys, no data leaves your computer.

**Stack:** FastAPI (Python) backend · LangGraph parallel agent graph · pluggable LLM providers (Ollama default; Claude/OpenAI via one env var) · React + Vite frontend · SQLite/SQLAlchemy data layer · matplotlib charts · pytest (168 tests) · Docker Compose · GitHub Actions CI.

---

## 2. What's inside, the complete inventory

### Backend (`backend/`)

**The agent** (`app/agent/`), the brain.

| File | What it does |
| --- | --- |
| `graph.py` | Two `StateGraph`s and the heart of the project. The **worker** graph is the classic loop (`plan` → `run_sql` / `run_python` / `make_chart` → back to `plan`) scoped to one sub-question. The **orchestrator** graph wraps it: `decompose` → several workers running in parallel → `merge` → `verify` → `interpret`, with a bounded retry edge from `verify` back to `decompose`. Also holds `run()` / `stream()`. |
| `state.py` | Two shapes. `AgentState` is the orchestrator's; `BranchState` is one worker's private world (its own sub-question, its own DataFrame) and never leaves it. Fields several branches write at once, `branches`, `trace`, carry additive reducers so parallel updates append instead of overwriting. |
| `prompts.py` | System prompts for the planner and each skill, written to be reliable with small local models (forced code fences, strict output rules). |
| `providers.py` | The provider registry. `LLM_PROVIDER` picks ollama/anthropic/openai at runtime; each provider is one registered builder function, SDKs import lazily, and outages get classified into readable `ProviderError`s. |
| `llm.py` | What the rest of the code calls: `complete()` for text, `structured()` for validated planner decisions, one cached client per (provider, model). No provider types leak past this file. |

**Skills** (`app/skills/`), the agent's capabilities, one module each. Every skill exposes `NAME`, `DESCRIPTION`, `run(...)` and returns a uniform `SkillResult`, so adding a capability means adding a file.

| File | What it does |
| --- | --- |
| `sql_skill.py` | Question → SQL via the LLM → **validate** → execute → on failure, feed the error back and retry (bounded). |
| `python_skill.py` | Generates a pandas snippet, validates it (AST), runs it in the sandbox. |
| `chart_skill.py` | Generates matplotlib code, runs it headless in the sandbox, returns the figure as a base64 PNG. |
| `interpret_skill.py` | Writes the final answer grounded strictly in the gathered results. |
| `base.py` | Shared `SkillResult` dataclass + fenced-code-block extraction (with a fallback for models that forget the fence). |

**Hooks** (`app/hooks/`), cross-cutting guardrails wrapped around every step.

| File | What it does |
| --- | --- |
| `safety.py` | The security core. `validate_sql`: single statement, `SELECT`/`WITH` only, token-level keyword blocklist, auto-`LIMIT`. `validate_python`: AST walk rejecting imports, dunder access, `eval`/`exec`/`open`/`getattr`/... |
| `cost.py` | `BudgetTracker`, caps total work at `MAX_AGENT_STEPS`. One tracker is shared by every parallel branch, so it's lock-protected. |
| `logging_hook.py` | Structured logging of every step. |

**Data & services**

| File | What it does |
| --- | --- |
| `data/connectors.py` | SQLAlchemy engines for CSVs (loaded into in-memory SQLite) and external databases; schema introspection; `to_json_records()`, the JSON-safe row sanitizer; and the per-engine read lock that keeps parallel branches from corrupting each other's results (see §7). |
| `services/session.py` | In-memory session registry with a cap (LRU eviction) and a TTL, so a long-running server doesn't collect dead engines. |
| `services/sandbox.py` | Restricted `exec` environment: only `df`/`pd`/`np`(/`plt`) visible, ~20 allow-listed builtins, copied DataFrame, captured stdout, headless matplotlib. |
| `main.py` | The FastAPI app: upload/connect/sample endpoints, sync + **SSE streaming** query endpoints, request ids on every response, timing logs, an upload size cap, and a JSON 500 handler that echoes the request id. |
| `schemas.py` / `config.py` | API models; settings (all overridable via environment variables). |

**Tests** (`tests/`), 168 tests, LLM fully mocked so they run anywhere (including CI) without Ollama: guardrails, sandbox, data layer, API endpoints, the worker loop (re-analyse cycle, fallback, budget), the orchestration layer (decomposition, genuine thread-level parallelism, the shared budget under concurrency, branch isolation, verifier retries and their bound, one branch failing without sinking the rest), streaming serialization regressions, provider selection/outages, session eviction, and the server limits.

**Sample data**, `data/samples/sales.csv`: 1,400 synthetic sales orders (2024-01 → 2025-10) across 4 regions, 4 categories, 3 customer segments, with realistic trend, seasonality, and 12 deliberate NULLs in `sales_rep` (which, it turns out, earn their keep, see §7).

### Frontend (`frontend/`)

React + Vite single-page app, deliberately dependency-light (React + React-DOM only).

| File | What it does |
| --- | --- |
| `src/App.jsx` | State owner: dataset session, message feed, streaming wiring, conversation history for follow-ups. |
| `src/api.js` | API client. `EventSource` can't POST, so it reads the fetch body and parses SSE frames manually. |
| `src/components/DataUpload.jsx` | Onboarding: load sample / upload CSV / connect a database. |
| `src/components/ChatPanel.jsx` | Feed, suggestion chips, composer (Enter to send). |
| `src/components/AgentTrace.jsx` | **The signature element**: the dark "machine room" panel. An orchestrator rail (Decompose → Merge → Verify → Answer) with branch lanes that appear the moment the graph fans out and light up independently as each worker progresses, the parallelism made visible, not described. |
| `src/components/ResultView.jsx` | Answer, then each branch's chart, result table and collapsible SQL/Python, labelled per branch only when there's more than one, so a simple question still reads as a plain answer. |
| `src/index.css` | The design system: light graph-paper workspace + dark trace rail, Space Grotesk / Inter / JetBrains Mono, responsive, reduced-motion aware. |

### Repository infrastructure

`README.md` (portfolio front page) · `docs/architecture.md` (engineering deep-dive) · `docs/images/` (real charts produced by the pipeline) · `docker-compose.yml` (ollama + backend + frontend) · `Makefile` · `.github/workflows/ci.yml` (ruff + pytest + frontend build) · Dockerfiles + `nginx.conf` · `.env.example` files · MIT `LICENSE`.

---

## 3. How it works, the life of one question

Say the dataset is loaded and you ask: *"Show revenue by region and revenue by category, both as charts."*

1. **The browser** POSTs to `/api/query/stream` with your question, the session id, and the last few Q&A turns (for follow-ups).
2. **FastAPI** looks up the dataset session and starts the **LangGraph run** on a background thread, streaming Server-Sent Events back as nodes complete.
3. **`decompose`** reads the question and decides it contains two independent parts: revenue by region, and revenue by category. (Most questions are one part, it only splits when the parts genuinely don't depend on each other.) The trace shows *"Split into 2 parallel tasks"*.
4. **Fan-out.** One `Send` per sub-question, and LangGraph runs them **concurrently on separate threads**. Two branch lanes appear in the trace panel.
5. **Each branch runs its own agent loop**, in its own isolated state: its planner picks `sql` → the SQL skill writes a query, the guardrail validates it's a single read-only statement and appends a `LIMIT`, it executes, rows get sanitized to JSON-safe records → back to its planner, which notices this branch is expected to produce a chart → the chart skill writes matplotlib code, the AST guard checks it, the sandbox runs it headless → back to the planner → done. Both branches do this **at the same time**, and their steps stream in interleaved (you'll literally see two `plan` steps arrive back to back, then two `sql` steps).
6. **`merge`** is the join point. The reducer has already collected both branch summaries; the trace reports *"2 branches finished"*.
7. **`verify`** takes a second look: do these results actually answer what was asked? If something explicitly requested is missing, it routes **back to `decompose`** with a note about the gap, a bounded number of times, so it can't loop. If it's satisfied, the run continues.
8. **`interpret`** writes the final answer from all the branches' results, using *only* the numbers that were actually computed (the prompt forbids inventing figures).
9. **The UI** receives the `final` event: the answer, each branch's chart and table, the SQL and Python behind them, and the verification verdict, while the trace panel shows the whole graph that produced it.

A simple question, *"what is total revenue by region?"*, takes the same path but decomposes to one branch, which makes it behave exactly like the original single loop. The extra machinery only shows up when it's earning its keep.

The sync endpoint `/api/query` does all of the same without streaming (useful for scripts and tests).

## 4. Running it from scratch

You need three things installed: **Python 3.11+**, **Node.js 18+**, and **Ollama**.

### Choosing a provider (optional)

The app defaults to Ollama and needs nothing else. All three provider packages
ship in `requirements.txt`, so to run the same agent on a hosted model instead:
set `LLM_PROVIDER=anthropic` (or `openai`) plus the matching API key, and start
the backend as usual, skip the Ollama steps entirely in that case. `LLM_MODEL`
overrides the default model for any provider, and `OPENAI_BASE_URL` lets the
openai provider talk to LM Studio, vLLM, Groq or any OpenAI-compatible server.
The pill in the UI header always shows who's answering.

### Step 0, Ollama and the model (once)

1. Install Ollama from https://ollama.com/download (Windows installer available; it runs in the background).
2. Pull the default model:

```bash
ollama pull qwen2.5
```

That's a ~4.7 GB download. Any tool-capable model works, set `OLLAMA_MODEL` to experiment. Bigger models write noticeably better SQL; smaller ones lean harder on the retry/fallback machinery (which is fun to watch in the trace panel).

### Step 1, Backend

**Windows (PowerShell):**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1     # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**macOS / Linux:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Leave this terminal running. Sanity check: http://localhost:8000/api/health should return `{"status":"ok","model":"qwen2.5"}` (interactive API docs live at http://localhost:8000/docs).

### Step 2, Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

### Step 3, Use it

Open **http://localhost:5173** → **Load sample dataset** → try:

- *What is total revenue by region?*
- *Show the monthly revenue trend as a chart*
- *Which product has the highest average discount?*
- *Compare revenue by customer segment as a bar chart*

Watch the right-hand trace panel while it runs, that's the agent thinking.

### Docker alternative

```bash
docker compose up --build
docker compose exec ollama ollama pull qwen2.5   # once
```

Frontend at http://localhost:5173, API at :8000, Ollama at :11434.

### Running the tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest        # 168 tests; no Ollama needed (LLM is mocked)
ruff check app tests list_models.py    # lint
```

---

## 5. Configuration reference

Set as environment variables or in `backend/.env` (copy from `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | `ollama`, `anthropic`, or `openai` |
| `LLM_MODEL` | provider default | Override the model for any provider |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | |  Only when using a hosted provider |
| `OPENAI_BASE_URL` | |  Any OpenAI-compatible server (LM Studio, vLLM, ...) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama listens |
| `OLLAMA_MODEL` | `qwen2.5` | Ollama's default model |
| `LLM_TEMPERATURE` | `0.0` | Deterministic output |
| `LLM_REQUEST_TIMEOUT` | `120` | Seconds per LLM call (old OLLAMA_* names still work) |
| `MAX_AGENT_STEPS` | `16` | Total planner steps, shared across every branch |
| `MAX_PARALLEL_BRANCHES` | `3` | Most sub-questions at once (`1` = classic single loop) |
| `MAX_VERIFY_PASSES` | `1` | How often the verifier may send work back |
| `ENABLE_VERIFIER` | `true` | Turn verification off entirely |
| `MAX_UPLOAD_MB` | `25` | Reject bigger uploads with a 413 |
| `MAX_SESSIONS` | `24` | Oldest session evicted past this |
| `SESSION_TTL_MINUTES` | `120` | Idle sessions expire |
| `LOG_LEVEL` | `INFO` | App log verbosity |
| `MAX_AGENT_STEPS` | `8` | Hard cap on planner loops |
| `MAX_SQL_ROWS` | `1000` | Row limit appended to queries |
| `SQL_RETRY_ATTEMPTS` | `1` | Extra tries after failed SQL |

---

## 6. Verification report, how this build was checked

Every claim below was executed, not assumed:

- **168/168 backend tests pass**, guardrails, sandbox, data layer, API, the worker loop, the orchestration layer (decomposition, parallelism, verifier, isolation), serialization regressions, provider selection/caching/outages, session eviction and TTL, upload cap, the 500 handler. The suite was also re-run from a fresh unzip of the final artifact.
- **Lint clean** (`ruff`) and every Python file compiles.
- **Frontend `npm ci` from the shipped lockfile + production build**: zero errors, exactly what the CI pipeline runs.
- **Live end-to-end over real HTTP**: a fake Ollama server implementing the real chat protocol (NDJSON streaming + structured output) was stood up, the real backend pointed at it, and the full stack driven with an adversarial question producing NULL groups, integer columns and a chart. The complete loop ran (`plan → sql → plan → chart → plan → interpret`), and every SSE frame passed **browser-strict** JSON parsing.
- **Parallelism verified live, not assumed**: a compound question driven through the real backend over HTTP fanned out to two branches that ran on separate threads, and the SSE stream showed their steps interleaved (`plan, plan, sql, sql`) rather than batched, the visible signature of genuine concurrency. A simple question in the same run stayed on a single branch.
- **Provider switching verified live**: the same backend booted with `LLM_PROVIDER=anthropic` (deliberately bad key) reports the right provider on `/api/health` and answers queries with the readable could-not-reach message instead of a 500; a bogus provider name gets the valid-options message. Construction of the real ChatAnthropic/ChatOpenAI clients is covered by tests.
- **Threading verified**: 32 genuinely parallel cross-thread queries against a connected SQLite file, zero errors.
- YAML configs parse; README image links resolve; no TODO/FIXME markers anywhere.

## 7. Bugs found and fixed along the way

Kept here deliberately, they're the most instructive part of the build.

**1. In-memory database invisible to the server's threads.** An in-memory SQLite engine defaults to a *per-thread* connection pool, and FastAPI serves sync endpoints from a threadpool, so the thread answering `/api/query` saw an empty database. Worked in single-threaded scripts, broke in the real server. **Fix:** `StaticPool` + `check_same_thread=False`, sharing one connection across threads. Locked in by the API test suite.

**2. Invalid JSON on the streaming path.** `DataFrame.to_dict()` records can contain `NaN`, which `json.dumps` emits as a bare `NaN` literal, Python's own parser tolerates it, but a browser's `JSON.parse` rejects it. Any query touching the sample data's 12 NULL `sales_rep` values would have broken the UI. Same class of bug: `numpy.int64` and `pandas.Timestamp` (from real Postgres/MySQL connections) would crash `json.dumps` outright. **Fix:** `to_json_records()` routes rows through pandas' own JSON encoder (NaN→`null`, numpy→native, datetimes→ISO) at the source, for both the stream and dataset previews. Four regression tests with a browser-strict parser now guard this, and the live e2e proves it over real HTTP.

**3. Parallel chart rendering deadlocking the whole request.** The worst one, and it only existed for a few hours. `matplotlib.pyplot` keeps global figure state and isn't thread safe, so once two branches could draw at the same time, they hung, permanently. One figure came back and the other threads never returned. The test suite missed it entirely because the parallelism tests happened to use SQL-only branches. Fix: all plotting, right through to encoding the PNG, happens under one lock. Verified with 40 concurrent renders checking that bars stay bars and lines stay lines.

**4. A sandbox escape straight onto the filesystem.** The AST guard was looking for `open`, `__import__` and `eval`, and missed that pandas *is* a filesystem library. `df.to_csv("/tmp/pwned.csv")` is an ordinary attribute call on a name the snippet is supposed to have, so it passed validation and **wrote real files**. `pd.read_csv` read arbitrary paths, and `to_pickle`/`read_pickle` is a full arbitrary-code-execution route. Fix: the pandas/numpy readers, writers and eval entry points are named and blocked, while everything that only moves data in memory stays allowed.

**5. No limit on how long generated code could run.** Nothing rejected `while True:`. Worse than a hung request: in CPython a tight loop starves every other thread of the GIL, so one bad snippet freezes the whole server. Fix: a watchdog that checks the clock between Python lines and stops the snippet at `SANDBOX_TIMEOUT_SECONDS`.

**6. Parallel branches silently corrupting each other's data.** The nastiest one, found by stress-testing *before* shipping the parallelism. In-memory engines use `StaticPool`, one SQLite connection shared by every thread, which is what makes an uploaded table visible across FastAPI's threadpool at all. But concurrent reads through that single connection interleave cursors and hand each other's rows over. Queries that must return 4, 4, 3 and 14 rows came back with 0, 5, 11 and 17; a full-table fetch of a 1,400-row table returned 2,714 rows. **No exception was raised**, just wrong numbers, in a tool whose whole job is correct numbers. Fix: reads on shared-connection engines are serialised behind a per-engine lock, while real databases (connection per thread) stay genuinely concurrent. The cost is negligible because SQLite queries take milliseconds and the model calls around them take seconds.

**7. The shared step budget losing count across threads.** Every branch shares one `BudgetTracker`, so the cap covers total work. But `self.steps += 1` isn't atomic, and with three branches bumping it concurrently, steps went missing and the budget could overrun. Fixed with a lock; a test asserts every planner step gets a unique number.

**8. The 500 that lost its request id.** The first version of the global error handler worked, but its responses were built outside the request middleware, so crashes were the one case *without* an `X-Request-ID` header, which is exactly when you want it. Fix: catch in the middleware itself so every response, including failures, takes the same exit. A test pins the header to the body's `request_id`.

**9. A dataset evicted mid-query** escaped as a bare `KeyError`, which the API turned into a 500. It now reads as a plain "that dataset is no longer loaded, load it again" response on both endpoints.

**10. Verified non-bug.** File-based SQLite via `/api/connect` was suspected of the same threading issue, 32 parallel cross-thread queries proved SQLAlchemy 2.0's pooling handles it correctly. No change needed; the test that proves it stays in the suite.

---

## 8. Troubleshooting

| Symptom | Cause & fix |
| --- | --- |
| Answers fail instantly; backend log shows connection errors to `11434` | Ollama isn't running. Start the Ollama app (Windows/macOS) or `ollama serve` (Linux). |
| Error mentioning the model is not found | Model not pulled: `ollama pull qwen2.5` (or whatever `OLLAMA_MODEL` is set to). |
| `Activate.ps1 cannot be loaded` on Windows | PowerShell policy: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| Port 8000 or 5173 already in use | Run with another port (`uvicorn ... --port 8001`; `npm run dev -- --port 5174`) or stop the other process. |
| First answer is very slow | The model loads into RAM on first use; subsequent questions are much faster. Keep Ollama running. |
| Answers are wrong or SQL keeps failing | Small local models are weak at SQL, watch the trace: you'll see retries and fallbacks doing their job. Try a bigger model (`OLLAMA_MODEL=qwen3` etc.) or switch providers. |
| "needs the langchain-... package" | You set `LLM_PROVIDER` to a hosted provider without installing its package, the message contains the exact pip command. |
| Answer says the provider couldn't be reached | Exactly what it sounds like: bad/missing API key, or Ollama down. The message names the provider and model so you know which config to check. |
| `npm install` complains about Node | Node 18+ required (`node -v`). |
| Uploaded file rejected | Only `.csv`/`.tsv` are accepted, and the file must have rows. |

---

## 9. Extending it

**Add a skill** (e.g. forecasting): create `app/skills/forecast_skill.py` with `NAME`, `DESCRIPTION`, `run(...) -> SkillResult`; register it in `app/skills/__init__.py`; add a node + loop-back edge in `app/agent/graph.py`; add the action to the planner prompt. The trace panel picks it up automatically.

**Swap the LLM provider**: edit `app/agent/llm.py` only, replace `ChatOllama` with any LangChain chat model.

**Ideas queued in the README roadmap**: cross-question DataFrame memory, multi-table joins, result caching, exporting a run as a notebook.

---

## 10. Publishing to GitHub

```bash
cd prism-data-agent
git init
git add .
git commit -m "Prism: LangGraph + FastAPI + React, local-first via Ollama"
git branch -M main
git remote add origin https://github.com/asadaslam556/prism-data-agent.git
git push -u origin main
```

CI runs automatically on the first push: lint, 168 tests, frontend build.

---

## 11. Design notes

The strongest threads to pull on:

- **"I built the orchestration explicitly."** Not a prebuilt ReAct helper, a LangGraph state machine whose loop, fallback and budget are unit-tested properties. The UI trace is the literal execution path.
- **"Local models forced better engineering."** Weaker SQL meant validation, retries with error feedback, heuristic fallbacks, and a step budget, the system assumes the model will fail and stays safe anyway.
- **"Running generated code is the real risk, and it's layered."** AST guard before execution, allow-listed builtins during, bounded loop around, plus an honest README note about what a hardened deployment would add.
- **"Testing without the model."** 168 tests with the LLM mocked verify everything around it; a fake Ollama server verifies the real client protocol end-to-end. Model quality changes answers, not safety.
- **"It's a graph of agent loops, not one loop."** The orchestrator decides how many independent sub-questions a request contains, runs a worker for each concurrently, merges them, and hands the result to a *separate* verifier, rather than the planner that did the work grading itself. Each branch keeps its own isolated state; only summaries cross back. Simple questions still collapse to one branch, so the complexity only appears when it earns its keep.
- **"Adding parallelism is where the real bugs live."** Threads surfaced a deadlock in matplotlib's global state, silent data corruption in the shared SQLite connection, and a lost-update race in the step counter, all found by stress-testing rather than by the test suite, all fixed at the source, all pinned by regression tests.
- **"The guard was looking for the wrong thing."** The sandbox blocked `open` and `__import__` but let `df.to_csv()` write files, because pandas is a filesystem library and that's just an attribute call. A denylist only covers what you thought to look for, which is exactly why SECURITY.md names the gaps instead of claiming there aren't any.
- **"Swapping the model is one env var."** A provider registry with lazy SDK imports keeps the default install local-only, while the same agent runs on Claude or GPT unchanged, and outages of any provider degrade to a readable answer, not a 500.
- **The bug stories in §7**, concurrency, serialization and middleware-ordering issues that only surface under real server conditions, found by adversarial verification, fixed at the source, locked in with regression tests.