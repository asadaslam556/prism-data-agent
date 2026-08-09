# Changelog

## 1.5.0

Renamed to Prism. The release is mostly about the agent wasting fewer calls and
the UI telling the truth about what happened.

### Added
- KPI cards. A query that returns one row of headline figures now renders as
  cards in the UI instead of being handed to the chart code, so it looks the
  same on every run rather than depending on what the model chose to draw.
- The model is told each column's type (`region (text)`, `revenue (number)`).
  It used to get bare names, guess, and call `.mean()` on a text column.
- Both the python and chart prompts now say there is no seaborn, scipy or
  sklearn and list the pandas/numpy equivalents. Heatmap requests reliably
  reached for `import seaborn`, got blocked, and burned a retry.

### Fixed
- **A recovered retry no longer reads as a failure.** The guard rejecting a
  first attempt is normal, the planner tries again and usually succeeds. It was
  being written to the branch's permanent `error` field, so a perfectly good
  answer showed a red error above it. It is now tracked separately and shown in
  the trace as a retry.
- Sub-question de-duplication now spans verifier retries. It only compared
  within a single decompose pass, so a retry could re-run a reworded version of
  work already finished, charting and billing it twice.
- An empty fan-out routes to merge. If de-duplication removed every sub-question
  a retry proposed, LangGraph skipped merge and verify entirely and the run
  ended with no answer.
- An explicitly requested chart type is honoured. Asking for a bar chart on
  time-series data still produced a line, because an earlier fix forced all
  time series to lines.

## 1.4.0

### Added
- `list_models.py`. Asks the configured endpoint which models it actually
  serves and tells you whether your current `LLM_MODEL` is among them. Handles
  flat lists and catalogues grouped by API family.
- `ANTHROPIC_MODEL` and `OPENAI_MODEL` are read as fallbacks below `LLM_MODEL`.
  The key and base URL already had per-provider fallbacks, so setting the model
  the same way looked like it should work. It was silently ignored.
- A model the endpoint doesn't serve gets its own error message pointing at
  `list_models.py`, rather than the generic "check the API key" text.

### Fixed
- The test suite is now hermetic. It read both `backend/.env` and any
  `ANTHROPIC_*` / `OPENAI_*` variables in the developer's shell, so it failed on
  a configured machine and passed on a clean clone. The shared fixture now pins
  settings and clears those variables.

## 1.3.0

The UI stopped being a side panel and became part of the conversation.

### Added
- The agent's reasoning now sits under each answer as a collapsible block,
  expanded with a live spinner while running and folded to
  "Thought for 4 steps · 6.2s" when done. It used to be a fixed panel that only
  ever showed the most recent run, so scrolling back to an older answer showed
  reasoning for a different question.
- Bar and line charts are redrawn as interactive SVG. Hovering reads the exact
  value. Shapes that can't be reproduced faithfully fall back to the image the
  agent drew.
- Answers render as markdown. They were printed raw, so headings and bold
  showed as literal `#` and `**`.
- Branches are labelled "Task 1", "Task 2" in the UI instead of the
  zero-indexed internal name.

### Fixed
- The chat column collapsed to its content width and sat against the left edge,
  leaving most of the window empty. It also explains the scrollbar appearing to
  float in the middle of the page.
- Charts: rotated labels ran off the canvas, categories were drawn as line
  charts, and the model's own chart type was ignored.
- The decomposer no longer emits a broad catch-all sub-question alongside the
  specific ones that make it up, which ran the same query twice.

### Changed
- All three LLM providers moved from optional to required in
  `requirements.txt`. Switching `LLM_PROVIDER` used to give an ImportError.

## 1.2.2

### Fixed
- **`ANTHROPIC_BASE_URL` was documented but never read**, so anyone pointing the
  app at a compatible endpoint got a confusing authentication failure against
  the public API instead. The first fix introduced a regression of its own,
  passing `base_url=None` explicitly overrides the SDK's own default, which is
  now pinned by a test.
- `LLM_MAX_TOKENS` caps what the model may write per call. Left unbounded, a
  reasoning model spends thousands of tokens thinking before writing a line of
  SQL and blows the per-call timeout. One question is roughly six sequential
  calls, so per-call latency multiplies.
- `LLM_TEMPERATURE` can be left blank to omit the parameter entirely. Some
  hosted models reject it with a 400 saying it is deprecated, and no value
  satisfies them.
- A request the endpoint refuses is now told apart from an outage. Retrying a
  refused request just burns steps before failing the same way, so it stops
  immediately with a message naming the setting to change.

## 1.2.1

A verification pass over 1.2.0 that turned up four real bugs, three of them
only reachable now that branches run in parallel.

### Fixed
- **Parallel chart rendering deadlocked the request.** pyplot keeps global state
  and is not thread safe; two branches drawing at the same time would hang
  forever, with one figure returned and the rest of the threads stuck. All
  plotting, right through to encoding the PNG, now happens under one lock.
- **A sandbox escape onto the filesystem.** `df.to_csv("/tmp/x")` is an ordinary
  attribute call on an allowed name, so it passed the AST guard and wrote real
  files. `pd.read_csv` read arbitrary paths and `to_pickle`/`read_pickle` is an
  arbitrary-code-execution route. The pandas/numpy readers, writers and eval
  entry points are now named and blocked.
- **No cap on how long a snippet could run.** Nothing rejected `while True:`,
  which hung the request and starved every other thread of the GIL. A watchdog
  now stops snippets at `SANDBOX_TIMEOUT_SECONDS` (default 30).
- **A dataset evicted mid-query escaped as a bare KeyError**, i.e. a 500. It now
  reads as a normal "that dataset is no longer loaded" response, on both the
  sync and streaming endpoints.
- `df['x'].values.mean()` and `.to_numpy()` used to fail with a confusing
  `KeyError: '__import__'`, because numpy imports lazily partway through. The
  sandbox now provides a narrow `__import__` that only returns already-loaded
  numpy/pandas internals.

### Added
- 33 new tests (122 total): parallel chart rendering, concurrent database reads,
  the shared step counter under threads, the watchdog (including that it hands
  tracing back), every filesystem escape route, and vanished sessions.
- `SANDBOX_TIMEOUT_SECONDS` setting.
- SECURITY.md now names the residual gaps rather than implying there are none.

## 1.2.0

The agent stopped being one loop and became a graph of loops.

### Added
- **Decomposition and parallel branches.** A new orchestrator level splits a
  question into independent sub-questions and runs one worker per part
  concurrently, on real threads. Each worker is the original agent loop,
  unchanged in spirit, with its own isolated state. Simple questions still
  resolve to a single branch and behave exactly as before.
- **A verifier node.** After the branches merge, a separate node checks whether
  the gathered results actually answer the question, and can send the work back
  for a bounded number of extra passes. It is a second opinion rather than the
  planner grading its own homework, and it can be switched off.
- Live interleaved streaming: nodes now push steps into a queue as they finish,
  so parallel branches report as they happen instead of arriving in a lump when
  a branch completes. Trace entries carry their branch id.
- The UI shows the graph: an orchestrator rail (decompose / merge / verify /
  answer) with branch lanes that appear on fan-out and light up independently,
  and results grouped per branch.
- `branches` and `verification` in the query response. The previous
  single-result fields are still there and point at the first branch that
  produced each kind of output, so anything built on the old shape keeps working.
- New settings: `MAX_PARALLEL_BRANCHES`, `MAX_VERIFY_PASSES`, `ENABLE_VERIFIER`.
- 18 new tests (89 total) covering decomposition, genuine thread-level
  parallelism, the shared budget under concurrency, branch isolation, verifier
  retries and their bound, and one branch failing without sinking the rest.

### Fixed
- **Silent data corruption under concurrent reads.** In-memory engines share one
  SQLite connection (`StaticPool`), and parallel branches reading through it
  interleaved cursors and returned each other's rows, no exception, just wrong
  numbers. Reads on shared-connection engines are now serialised behind a
  per-engine lock; real databases are unaffected. Found by stress-testing before
  the parallelism shipped.
- `BudgetTracker` is thread-safe. Branches share one counter, and `+= 1` across
  threads was dropping steps and overrunning the cap.
- A branch flagged as needing a chart now tells its planner so, instead of
  relying on the sub-question wording happening to mention one.

### Changed
- `MAX_AGENT_STEPS` default raised from 8 to 16, since the budget is now shared
  across all branches rather than spent by a single loop.

## 1.1.0

### Added
- Pluggable LLM providers. `LLM_PROVIDER` picks ollama (default), anthropic,
  or openai; `LLM_MODEL` overrides the per-provider default; `OPENAI_BASE_URL`
  covers any OpenAI-compatible server (LM Studio, vLLM, Groq). New providers
  are one registered function in `app/agent/providers.py`.
- Friendly degradation when the model backend is down: instead of a 500 with
  a stack trace, the API returns a normal response explaining what to check
  ("is Ollama running, is the model pulled"). The stream ends with a clean
  `final` event either way.
- Request ids (`X-Request-ID`) on every response, per-request timing logs, and
  a JSON 500 handler that echoes the id so logs and bug reports can be matched.
- Server limits: upload size cap (413 past `MAX_UPLOAD_MB`), session cap with
  LRU eviction, and a session TTL. Evicted sessions dispose their engines.
- Provider/model pill in the UI header, fed by the richer `/api/health`.
- `LOG_LEVEL` setting; the app logger no longer touches the root logger and
  httpx request noise is silenced.
- Docker hardening: non-root backend user, `.dockerignore` files, compose
  healthchecks. CI now tests on Python 3.11 and 3.12.
- 20 new tests (71 total): provider selection and caching, outage
  classification, graceful-failure paths, eviction/TTL, upload cap, the 500
  handler, request ids.
- CONTRIBUTING.md, SECURITY.md, this changelog.

### Changed
- `OLLAMA_TEMPERATURE` / `OLLAMA_REQUEST_TIMEOUT` became `LLM_TEMPERATURE` /
  `LLM_REQUEST_TIMEOUT` (old names still accepted, nothing breaks).
- Comments and docstrings rewritten throughout to read like working notes
  rather than generated boilerplate.

## 1.0.0

Initial release: LangGraph agent (plan / sql / python / chart / interpret with
a re-analyse loop and step budget), FastAPI backend with SSE streaming, React
analyst console with a live trace panel, SQL + Python guardrails and sandbox,
sample dataset, Docker Compose, CI, 51 tests.
