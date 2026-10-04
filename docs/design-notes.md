# Design notes

![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![pandas](https://img.shields.io/badge/pandas-150458?logo=pandas&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-11557C)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?logo=langgraph&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)

Bugs found while building Prism. They shaped the design more than anything else, so they're written down. Each fix is still in the code at the place named.

| # | Bug | Fix | Where |
| --- | --- | --- | --- |
| 1 | The in-memory database was invisible to the server's threads | `StaticPool` with `check_same_thread=False` | `data/connectors.py` |
| 2 | Invalid JSON on the stream | Rows go through pandas' JSON encoder | `connectors.to_json_records` |
| 3 | Parallel charts deadlocked the request | One lock around all plotting | `_PLOT_LOCK` in `services/sandbox.py` |
| 4 | Generated code could write files through pandas | File readers and writers blocked by name | `hooks/safety.py` |
| 5 | No limit on how long generated code could run | A line-tracing watchdog | `services/sandbox.py` |
| 6 | Parallel branches silently swapped each other's rows | A read lock per in-memory engine | `_lock_for` in `data/connectors.py` |
| 7 | The shared step budget lost count | A lock in the budget | `BudgetTracker` in `hooks/cost.py` |
| 8 | The 500 response lost its request id | Errors caught inside the request middleware | `main.py` |
| 9 | A dataset evicted mid-query became a 500 | A plain "no longer loaded" answer | `agent/graph.py` |
| 10 | The sandbox could reach `os` through the libraries | Module views, a stricter AST check and an audit hook | `services/sandbox.py`, `hooks/safety.py` |
| 11 | The row cap could be dodged | Only a trailing `LIMIT` counts, and it's clamped | `validate_sql` in `hooks/safety.py` |

Bugs 3, 6 and 7 only appeared once branches ran on real threads. Their fixes, plus a lock on the session registry, are the four locks parallel branches rely on:

![The four locks parallel branches need](images/concurrency-locks.svg)

## 1. The in-memory database was invisible to the server's threads

An in-memory SQLite engine defaults to a per-thread connection pool, and FastAPI serves sync endpoints from a threadpool, so the thread answering `/api/query` saw an empty database. It worked in scripts and broke in the server.

## 2. Invalid JSON on the stream

`DataFrame.to_dict()` can produce `NaN`, which `json.dumps` writes as a bare `NaN` literal. Python parses that; a browser's `JSON.parse` doesn't. Any query touching the sample's empty `sales_rep` values broke the UI. `numpy.int64` and `pandas.Timestamp` from a real database crashed `json.dumps` outright.

## 3. Parallel charts deadlocked the request

pyplot keeps global state and isn't thread-safe. Once two branches could draw at the same time, one figure came back and the other threads hung. The parallelism tests used SQL-only branches, so they missed it. Everything from drawing to encoding the PNG now happens under one lock.

## 4. Generated code could write files through pandas

The first guard looked for `open`, `__import__` and `eval`, and missed that pandas is a filesystem library. `df.to_csv("/tmp/x.csv")` is an ordinary method call on an allowed name, so it passed and wrote real files, and `to_pickle`/`read_pickle` was a route to running arbitrary code.

## 5. No limit on how long generated code could run

Nothing rejected `while True:`, and in CPython a tight loop starves every other thread, so one bad snippet froze the whole server. The watchdog checks the clock between lines and stops the snippet at `SANDBOX_TIMEOUT_SECONDS`.

## 6. Parallel branches silently swapped each other's rows

The in-memory engines share one SQLite connection across threads (that's the fix for bug 1). Concurrent reads through that connection interleaved their cursors. Queries that should have returned 4, 4, 3 and 14 rows came back with 0, 5, 11 and 17, with no exception. Reads on shared-connection engines now take a per-engine lock; real databases still run concurrently. The cost is small next to the model calls around each query.

## 7. The shared step budget lost count

`self.steps += 1` isn't atomic. With three branches incrementing it together, steps went missing and the budget overran.

## 8. The 500 response lost its request id

The global error handler built its response outside the request middleware, so crashes were the one response without an `X-Request-ID` header.

## 9. A dataset evicted mid-query became a 500

It surfaced as a bare `KeyError`. The run now ends with an answer saying the dataset is no longer loaded.

## 10. The sandbox could reach `os` through the libraries

pandas, numpy and pyplot import `os`, `sys` and `subprocess` at module level, so `pd.io.common.os.remove(...)` or `plt.sys.modules["subprocess"]` passed every check. So did a generator's `gi_frame.f_back.f_globals`, `df.query()` (pandas evaluates the string itself), and `df.apply("to_pickle", path=...)`, which writes a file without a single attribute node. The fix has three parts: read-only module views that won't return submodules, an AST check that rejects private attributes, frame introspection and method names passed as strings, and an audit hook that refuses file writes, processes and sockets at run time. Details in [SECURITY.md](../SECURITY.md#python).

## 11. The row cap could be dodged

The SQL guard only added a `LIMIT` when the word "limit" appeared nowhere, so a limit in a subquery or a comment left the outer query unbounded, and a model-chosen `LIMIT 100000` was kept.
