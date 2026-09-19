# Changelog

All notable changes to Prism. Versions follow [semantic versioning](https://semver.org).

## 1.7.0

A security and housekeeping release. The sandbox had real escape routes, and
they're closed.

### Security
- **The sandbox could reach `os` through the libraries it was given.** pandas,
  numpy and pyplot import `os`, `sys` and `subprocess` at module level, so
  `pd.io.common.os.remove(...)` and `plt.sys.modules["subprocess"]` passed every
  check and ran. Snippets now get read-only views of `pd`, `np` and `plt` that
  refuse to return submodules, apart from a short allowlist (`np.random`,
  `np.linalg`, `pd.api.types` and a few others).
- **More routes the AST guard missed:** frame introspection
  (`gen.gi_frame.f_back.f_globals`), `df.query()` (pandas evaluates the string
  itself, attribute access included), method names passed as strings
  (`df.apply("to_pickle", path=...)`), `ndarray.dump`, `canvas.print_png`,
  `pd.ExcelFile`, and matplotlib's backend loader, which imports any module by
  name. All rejected now, along with any private attribute.
- **A runtime backstop.** An audit hook refuses file writes, processes, sockets
  and ctypes while a snippet runs, however the call was reached.
- **The SQL row cap could be dodged.** A `LIMIT` in a subquery or a comment
  counted as "has a limit", leaving the outer query unbounded, and a model-chosen
  `LIMIT 100000` was kept. Only a trailing `LIMIT` counts now, clamped to
  `MAX_SQL_ROWS`.

### Fixed
- The UI waited forever if the stream closed without a final event (server
  restart, dropped connection). It now shows an error.
- Horizontal bar charts drew negative values from the axis minimum instead of
  from zero.
- An oversized upload was read fully into memory before being rejected. Only one
  byte past the limit is read now.
- The session registry is locked. FastAPI serves sync endpoints from a
  threadpool, and concurrent eviction could mutate it mid-iteration.
- Expired sessions are dropped when new ones load, not only when someone asks
  for them again, so abandoned engines don't pile up.
- A failed connection (say, a bad table name) no longer leaks its connection pool.
- `backend/.env` is found relative to the backend folder, not whatever directory
  the server was started from.

### Changed
- Two providers now: Ollama for local models, and `openai` for OpenAI or any
  compatible endpoint (DeepSeek, Groq, vLLM, LM Studio). The third hosted
  provider and its SDK are gone, which trims the install.
- Dependencies upgraded: React 19, Vite 8, pandas 3, numpy 2.4, FastAPI 0.141
  and the rest of the Python stack. The frontend now needs Node 20.19 or newer.
  This also clears every open npm security advisory (vite, esbuild, postcss,
  browserslist, nanoid).
- Image metadata stripped from the app icons and screenshots.
- The guides moved into `docs/`: `docs/guide.md`, `docs/windows.md` and
  `docs/deploy-render.md`. All docs were revised for accuracy.
- CI builds the deployment image, and Dependabot now watches pip and npm as well
  as GitHub Actions.
- Removed code nothing used: the skills registry dict, unused budget metrics,
  and a state field that was written but never read.

## 1.6.1

### Fixed

- `llm.structured()` sent no explicit `method` to `with_structured_output()`,
  so LangChain used its response_format-based default. DeepSeek's API rejects
  that outright -- `response_format: {"type": "json_schema"}` comes back
  `400 This response_format type is unavailable now`, a documented limitation
  on their side, not an outage. Forced to `method="function_calling"` instead,
  which routes through `tools`/`tool_choice` and is what DeepSeek's own docs
  point to. One call site in `llm.py` feeds every structured call in the agent
  (decomposer, planner, verifier), so the one-line fix covers all three.
  Ollama was unaffected, since it already answers structured requests through
  tool calling.

- That fix traded one 400 for another. DeepSeek's V4 models run in thinking mode
  by default, and thinking mode refuses a *forced* tool choice -- which is
  exactly what `method="function_calling"` sends. The error changes to
  `400 Thinking mode does not support this tool_choice`. The cure is
  `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}`, which turns thinking off
  and is also faster, since none of the token budget goes to reasoning the agent
  never reads. The setting itself already shipped in 1.6.0; what was missing was
  anything telling you that DeepSeek needs it. Now documented in `README.md`,
  `backend/.env.example` and `RENDER.md`. Suppressing `tool_choice` instead was
  considered and rejected: it lets the model answer in plain text roughly half
  the time, which would make the planner unreliable.

- `backend/.env.example` claimed thinking mode was off by default and that
  blank meant non-thinking. Both were wrong for DeepSeek V4 and would have sent
  the next person down the same dead end.

## 1.6.0

Deployment. The app can now run as a single container and sit on a public URL
without being open to everyone who finds it.

### Added
- **One image serves both halves.** A root `Dockerfile` builds the React app and
  hands it to FastAPI, so there is one process, one port and no CORS to
  configure. `docker-compose.yml` is unchanged and still runs the three-service
  local stack with Ollama.
- **Optional browser login.** Set `APP_USERNAME` and `APP_PASSWORD` and every
  route, frontend included, sits behind an HTTP Basic prompt. Both blank means
  no prompt, so nothing changes locally. `/api/health` stays open for platform
  liveness checks.
- **`/api/connect` can be switched off** with `ENABLE_DB_CONNECT=false`, which
  the deployment image sets. It dials arbitrary URLs, which is a feature on a
  laptop and a request-forgery vector on a network.
- **`LLM_TOP_P` and `LLM_EXTRA_BODY`.** `extra_body` carries provider-specific
  switches the OpenAI schema has no field for, thinking mode being the one that
  matters. Shapes differ per provider and are not interchangeable.
- **Listens on `$PORT`** when the host sets one, 7860 otherwise. A hardcoded
  port means traffic arrives where nothing is bound and health checks fail.
- Eight tests for the login path, including malformed headers and passwords
  containing colons. 176 total.

### Fixed

- Credentials set in `backend/.env` were ignored. They were read straight from
  `os.environ`, and pydantic-settings loads a `.env` into the Settings object
  without touching the real environment, so the login looked configured and was
  silently off. Both sources work now.

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
- `OPENAI_MODEL` is read as a fallback below `LLM_MODEL`.
  The key and base URL already had per-provider fallbacks, so setting the model
  the same way looked like it should work. It was silently ignored.
- A model the endpoint doesn't serve gets its own error message pointing at
  `list_models.py`, rather than the generic "check the API key" text.

### Fixed
- The test suite is now hermetic. It read both `backend/.env` and any
  `OPENAI_*` variables in the developer's shell, so it failed on
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
- **A provider base URL was documented but never read**, so anyone pointing the
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
- Pluggable LLM providers. `LLM_PROVIDER` picks ollama (default) or openai; `LLM_MODEL` overrides the per-provider default; `OPENAI_BASE_URL`
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

## 1.0.0

Initial release: LangGraph agent (plan / sql / python / chart / interpret with
a re-analyse loop and step budget), FastAPI backend with SSE streaming, React
analyst console with a live trace panel, SQL + Python guardrails and sandbox,
sample dataset, Docker Compose, CI, 51 tests.