# Security

## The risky part

Prism runs SQL and Python written by a language model. That's the core feature and the core risk, and it's handled in layers so that getting past one still leaves the others.

1. **Static checks.** SQL must be a single `SELECT` or `WITH` statement with no write or admin keywords. Comments are stripped, and the query ends with a `LIMIT` no larger than `MAX_SQL_ROWS`, added or clamped as needed. Python is parsed and walked before it runs: no imports, no private or dunder attributes, no frame introspection (`gi_frame`, `f_globals` and so on), no `eval`/`exec`/`open`/`getattr`, and none of the pandas, numpy or matplotlib calls that read or write files, including `query()`, which evaluates its string argument itself. Method names passed as strings (`df.apply("to_pickle", ...)`) are rejected too.
2. **A restricted namespace.** Snippets run against a copy of the data with about twenty allow-listed builtins. They get read-only views of `pd`, `np` and `plt` rather than the modules themselves, because those libraries import `os`, `sys` and `subprocess` internally and any submodule used to be a way to reach them. The views return functions, classes and constants as normal but refuse to hand out a module, apart from a few numeric ones like `np.random` and `pd.api.types`. A narrow `__import__` returns already-loaded numpy and pandas internals, because numpy imports lazily partway through ordinary calls.
3. **An audit hook.** While a snippet runs, a [PEP 578](https://peps.python.org/pep-0578/) audit hook on that thread refuses file writes, process creation, sockets and ctypes. This catches what static checks can't read, like a method name assembled at runtime. Reads are allowed, because matplotlib opens its own font files while rendering.
4. **A watchdog.** No static check rejects `while True:`, and in CPython a tight loop starves every other thread of the GIL. Snippets are stopped once they pass `SANDBOX_TIMEOUT_SECONDS`.
5. **A bounded loop.** A step budget shared across all parallel branches, and a fixed number of verifier retries, so a stuck agent ends with a best-effort answer.
6. **Server limits.** Upload size cap, session cap with LRU eviction, session TTL, and a request id on every response.

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
