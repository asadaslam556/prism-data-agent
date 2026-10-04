# Security

![CodeQL](https://img.shields.io/badge/CodeQL-enabled-2F3237?logo=github&logoColor=white)
![Secret scanning](https://img.shields.io/badge/secret_scanning-on-2F3237?logo=github&logoColor=white)
![Dependabot](https://img.shields.io/badge/Dependabot-on-025E8C?logo=dependabot&logoColor=white)

## The risky part

Prism runs SQL and Python written by a language model. That's the core feature and the core risk, and it's handled in layers so that getting past one still leaves the others. Code: `backend/app/hooks/safety.py` and `backend/app/services/sandbox.py`.

### SQL

![How a generated query gets run](docs/images/sql-guard.svg)

The SQL skill asks the model for one query, written for the session's database. `validate_sql` then, in order:

1. **Strips comments**, so `-- no limit` can't count as a `LIMIT`.
2. **Requires exactly one statement.**
3. **Requires it to start with `SELECT` or `WITH`.**
4. **Rejects write and admin keywords** as whole words: `insert`, `update`, `delete`, `drop`, `alter`, `create`, `truncate`, `attach`, `detach`, `pragma`, `grant`, `revoke`, `vacuum`, `reindex`, `exec`, `execute`, `call`, `merge`, `copy`, `into`. Whole words, so a `discount` column isn't rejected for containing `count`. Words inside quoted values are skipped (`WHERE status = 'update pending'` is fine), except in a value containing a backslash, because databases disagree on where such a value ends. `REPLACE()` is allowed; `REPLACE INTO` is still caught by `into`.
5. **Caps the rows.** Only a trailing `LIMIT` counts, because one in a subquery doesn't bound the result. A missing `LIMIT` is added as `MAX_SQL_ROWS`; a larger one is clamped to it, including MySQL's `LIMIT offset, count` form.

A rejected query or a database error goes back to the model with the message, up to `SQL_RETRY_ATTEMPTS` extra tries (default 1). After that the step fails and the planner sees the error.

### Python

![Layers around model-written Python](docs/images/python-sandbox.svg)

The pandas and chart skills ask the model for one snippet that leaves its output in a variable called `result`. Four layers stand between that snippet and the server.

1. **An AST check** (`validate_python`). The snippet is parsed and walked before anything runs, and rejected for:
   - any `import`, or any attribute starting with `_`, private or dunder;
   - frame and code introspection: `gi_frame`, `f_back`, `f_globals`, `f_builtins`, `tb_frame` and the rest;
   - the names `eval`, `exec`, `compile`, `open`, `__import__`, `input`, `globals`, `locals`, `getattr`, `setattr`, `delattr`, `vars`;
   - methods that read or write files or evaluate strings: the pandas `to_*` writers and `read_*` readers, numpy's `save`/`load` family, matplotlib's `savefig`, and `query`, `eval`, `exec`, `system`, `popen`, including when the name is passed as a string, as in `df.apply("to_pickle", path=...)`.
2. **A restricted namespace.** The snippet gets a copy of the DataFrame as `df`, and read-only views of `pd`, `np` and `plt` rather than the modules themselves, because those libraries import `os`, `sys` and `subprocess` internally. The views return functions, classes and constants as usual but refuse to return a module, apart from a few numeric ones like `numpy.random` and `pandas.api.types`. There are 20 builtins (`len`, `range`, `min`, `max`, `sum`, `abs`, `round`, `sorted`, `list`, `dict`, `set`, `tuple`, `float`, `int`, `str`, `bool`, `enumerate`, `zip`, `print`, `isinstance`), and a narrow `__import__` that only returns already-loaded numpy, pandas and standard math and date modules, because numpy imports lazily partway through some ordinary calls.
3. **An audit hook.** While a snippet runs, a [PEP 578](https://peps.python.org/pep-0578/) audit hook on that thread refuses opening a file for writing, process creation, file removal and renaming, sockets, `ctypes`, `urllib` and `http`. This catches what the AST check can't read, like a method name assembled at run time. Reads are allowed, because matplotlib opens its own font files.
4. **A watchdog.** No static check rejects `while True:`, and in CPython a tight loop starves every other thread. A line tracer stops the snippet once it runs longer than `SANDBOX_TIMEOUT_SECONDS` (default 30).

A rejection, an error while running (including a blocked call) or a timeout comes back to the planner as a failed step, and it can try again or answer without that analysis.

### Limits around the agent

- **A bounded loop.** A step budget shared across all parallel branches, and a fixed number of verifier retries, so a stuck agent ends with a best-effort answer.
- **Server limits.** An upload size cap, a session cap with least-recently-used eviction, a session TTL, and a request id on every response.

## Continuous checks

Every push runs [CodeQL](https://codeql.github.com/) over the Python, JavaScript and workflow code, secret scanning with push protection is on, and Dependabot raises grouped update PRs for pip, npm and GitHub Actions every month. The regression tests for every sandbox escape found so far run in CI on Python 3.11 and 3.12.

## Known gaps

This is hardening for a local, single-user tool. CPython can't be made fully safe from inside its own process, and it's better to say where the edges are:

- **The watchdog can't interrupt a single long call in C.** It checks the clock between Python lines, so a runaway loop is stopped but one huge allocation (`[0] * 10**10`) can still hurt before it returns.
- **There is no memory cap.** Enforcing one properly means limiting the process, which would take the server down with it.
- **The static checks are a denylist.** They name the escape routes found so far. The module views and the audit hook narrow what a missed route can do, but reading data the process can already read (environment variables, files) isn't blocked at runtime.
- **`/api/connect` dials any URL it's given.** That's the feature, but on a network with internal services it's also a request-forgery vector. `ENABLE_DB_CONNECT=false` turns the endpoint off and keeps the sample and CSV upload; the deployment image does exactly that.
- **There is no rate limiting.** Nothing stops a logged-in user from asking a thousand questions, and on a hosted model each one costs money.

## Deploying it

Setting `APP_USERNAME` and `APP_PASSWORD` puts every route, frontend included, behind an HTTP Basic prompt. Both halves of the credentials are compared with `secrets.compare_digest` every time, so a wrong username doesn't return faster than a wrong password. `/api/health` stays open so a hosting platform can run its liveness check. Leave both blank, the default, and there's no prompt at all, which is right on a laptop.

Basic auth sends the credentials with every request, base64-encoded rather than hashed. That's fine over HTTPS, which managed hosts terminate for you, and not fine over plain HTTP. It keeps strangers out; it isn't a user system. There's one credential pair, no sessions and no lockout.

For untrusted or multi-tenant use you'd want more: run the execution step in a separate process or container with OS-level resource limits, connect databases with read-only credentials, keep secrets out of the process that runs generated code, and add a real rate limiter. None of that is included because it depends on where you deploy.

## Reporting a vulnerability

If you find a way through the guardrails, please report it privately through GitHub: the repository's **Security** tab → **Report a vulnerability**. Include the generated code that got through and what it managed to do. For anything minor that can't be used to cause harm, a regular issue is fine.
