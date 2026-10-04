# Guardrails

Prism runs SQL and Python written by a language model. This page covers every check that code passes through, in order. Code: `backend/app/hooks/safety.py` and `backend/app/services/sandbox.py`. Known gaps and how to report a vulnerability are in [SECURITY.md](../SECURITY.md).

**On this page:** [SQL](#sql) · [Python](#python) · [The step budget](#the-step-budget) · [What this is not](#what-this-is-not)

## SQL

[![How a generated query gets run](diagrams/sql-guard.architecture.svg)](diagrams/sql-guard.architecture.html)

The SQL skill asks the model for one query, written for the session's database (SQLite for uploads and the sample, otherwise PostgreSQL, MySQL and so on). `validate_sql` then, in order:

1. **Strips comments**, so `-- no limit` can't count as a `LIMIT`.
2. **Requires exactly one statement.**
3. **Requires it to start with `SELECT` or `WITH`.**
4. **Rejects write and admin keywords** as whole words: `insert`, `update`, `delete`, `drop`, `alter`, `create`, `truncate`, `attach`, `detach`, `pragma`, `grant`, `revoke`, `vacuum`, `reindex`, `exec`, `execute`, `call`, `merge`, `copy`, `into`. Whole words, so a `discount` column isn't rejected for containing `count`. Words inside quoted values are skipped (`WHERE status = 'update pending'` is fine), except in a value containing a backslash: databases disagree on where such a value ends, so it stays checked. `REPLACE()` is allowed; `REPLACE INTO` is still caught by `into`.
5. **Caps the rows.** Only a trailing `LIMIT` counts, because one in a subquery doesn't bound the result. A missing `LIMIT` is added as `MAX_SQL_ROWS`; a larger one is clamped to it, including MySQL's `LIMIT offset, count` form.

`run_select` then runs the query. On the in-memory engines it takes the per-engine read lock ([data.md](data.md#concurrency)).

A rejected query or a database error goes back to the model with the message, up to `SQL_RETRY_ATTEMPTS` extra tries (default 1). After that the step fails and the planner sees the error.

## Python

[![Layers around model-written Python](diagrams/python-sandbox.architecture.svg)](diagrams/python-sandbox.architecture.html)

The pandas and chart skills ask the model for one snippet that leaves its output in a variable called `result`. Four layers stand between that snippet and the server.

### 1. AST check (`validate_python`)

The snippet is parsed and walked before anything runs. It's rejected for:

- any `import` or `from … import`
- any attribute starting with `_`, private or dunder
- frame and code introspection: `gi_frame`, `f_back`, `f_globals`, `f_builtins`, `tb_frame` and the rest
- the names `eval`, `exec`, `compile`, `open`, `__import__`, `input`, `globals`, `locals`, `getattr`, `setattr`, `delattr`, `vars`
- methods that read or write files or evaluate strings: the pandas `to_*` writers and `read_*` readers, numpy's `save`/`load` family, matplotlib's `savefig`, backend loaders and `pause`, and `query`, `eval`, `exec`, `system`, `popen`
- those method names passed as strings, as in `df.apply("to_pickle", path=...)`

### 2. Restricted namespace

The snippet runs with:

- a **copy** of the DataFrame as `df`
- **read-only module views** of `pd`, `np` and (for charts) `plt`. They return functions, classes and constants as usual but refuse to return a module, so `pd.io.common.os` is unreachable. The only submodules they hand out are `numpy.random`, `numpy.linalg`, `numpy.fft`, `numpy.ma`, `pandas.api`, `pandas.api.types`, `pandas.tseries`, `pandas.tseries.offsets`, `matplotlib.cm`, `matplotlib.colors`, `matplotlib.ticker` and `matplotlib.dates`
- **20 builtins**: `len`, `range`, `min`, `max`, `sum`, `abs`, `round`, `sorted`, `list`, `dict`, `set`, `tuple`, `float`, `int`, `str`, `bool`, `enumerate`, `zip`, `print`, `isinstance`
- a **narrow `__import__`** that only returns already-loaded modules under `numpy`, `pandas`, `math`, `statistics`, `datetime`, `decimal` and `dateutil`, because numpy imports lazily partway through some ordinary calls

### 3. Audit hook

A [PEP 578](https://peps.python.org/pep-0578/) audit hook, active only on the thread while a snippet runs, refuses opening a file for writing and events under `os.system`, `os.exec*`, `os.spawn*`, `os.fork`, `os.remove`, `os.rename`, `os.mkdir`, `os.chmod`, `subprocess`, `shutil`, `socket`, `ctypes`, `urllib`, `http` and similar. It catches what the AST check can't read, like a method name assembled at run time. Reading files stays allowed, because matplotlib opens its own font files.

### 4. Watchdog

A line tracer stops the snippet once it runs longer than `SANDBOX_TIMEOUT_SECONDS` (default 30). Nothing static rejects `while True:`, and in CPython a tight loop would starve every other thread.

### When a layer says no

A rejection, an error raised while running (including a blocked call), or a timeout comes back to the planner as a failed step. The planner can try again or answer without that analysis. Chart drawing happens under one lock and every figure is closed afterwards, so nothing is left in pyplot's global state.

## The step budget

`MAX_AGENT_STEPS` (default 16) caps the planner steps for a whole question, shared across its branches, and `MAX_VERIFY_PASSES` caps the verifier's retries. A stuck agent ends with a best-effort answer instead of looping. See [agent.md](agent.md#the-step-budget).

## What this is not

This is hardening for a local, single-user tool, not a jail. CPython can't be fully locked down from inside its own process. The AST check is a denylist of the routes found so far; the module views and the audit hook limit what a missed route could do. There is no memory cap, and one long call inside C can't be interrupted. [SECURITY.md](../SECURITY.md) lists every known gap and what a multi-tenant deployment would need.
