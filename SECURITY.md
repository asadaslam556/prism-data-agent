# Security

## What this app does that's risky

It executes SQL and Python written by a language model. That's the core
feature and the core risk, and it's handled in layers:

1. **Static checks first.** SQL must be a single SELECT/WITH statement with no
   write/DDL keywords (token-level check, then a LIMIT gets appended). Python is
   AST-walked: no imports, no dunder access, no eval/exec/open/getattr, and no
   pandas/numpy calls that reach the filesystem. That last one is the easiest to
   overlook -- pandas is a filesystem library, and `df.to_csv("/etc/cron.d/x")`
   is an ordinary attribute call on a name the snippet is supposed to have. The
   readers and writers (`to_csv`, `read_pickle`, `np.save`, `savefig`, ...) are
   named and blocked; anything that only moves data around in memory is not.
2. **Constrained execution.** Approved snippets run in a namespace containing
   only `df`, `pd`, `np` (plus `plt` for charts) and about twenty allow-listed
   builtins, against a copy of the data, with stdout captured. The one exception
   is a narrow `__import__` that returns already-loaded numpy/pandas internals
   and refuses everything else -- numpy imports lazily partway through ordinary
   calls, and without it `df['x'].values.mean()` fails.
3. **A watchdog on execution time.** Nothing in the AST guard rejects
   `while True:`, and in CPython a tight loop doesn't just hang its own request,
   it starves every other thread of the GIL. Snippets are stopped once they pass
   `SANDBOX_TIMEOUT_SECONDS`.
4. **A bounded loop.** The planner has a hard step cap shared across all parallel
   branches, so a stuck agent ends with a best-effort answer instead of running
   forever, and the verifier can only send work back a fixed number of times.
5. **Server limits.** Upload size cap, session cap with LRU eviction, session
   TTL, request ids on every response.

## What it deliberately does not claim

This is hardening for a local, single-user tool. CPython cannot be made fully
safe from inside the process, and I'd rather name the gaps than imply there
aren't any:

- **The watchdog can't interrupt a single long call in C.** It checks the clock
  between Python lines, so a runaway loop gets stopped but one enormous
  allocation (`[0] * 10**10`) can still hurt before it returns.
- **There is no memory cap.** Same reason -- limiting it properly means limiting
  the process, which would take the server down with it.
- **The denylist is a denylist.** It names the pandas/numpy escape routes I found
  by going looking for them. A method I haven't thought of is a method that
  isn't on the list.
- **`/api/connect` will dial any URL you give it.** That is the feature, but on a
  network with internal services it is also a request-forgery vector. Set
  `ENABLE_DB_CONNECT=false` to turn the endpoint off and keep the sample and CSV
  upload; the deployment image in `Dockerfile` does exactly that.
- **There is no rate limiting.** Nothing stops one authenticated user asking a
  thousand questions, and on a hosted model each one costs money.

## Deploying it somewhere

Setting `APP_USERNAME` and `APP_PASSWORD` puts every route, the frontend
included, behind an HTTP Basic prompt. Credentials are compared with
`secrets.compare_digest`, both halves every time, so a wrong username doesn't
come back faster than a wrong password. `/api/health` stays open so a platform
can run its liveness check. Leave both blank -- the default -- and there is no
prompt at all, which is the right setting on a laptop.

Basic auth sends credentials on every request, base64-encoded, not hashed. That
is fine over HTTPS, which every managed host terminates for you, and not fine
over plain HTTP. It is a keep-strangers-out measure, not a user system: there is
one credential pair, no sessions and no lockout after repeated failures.

For untrusted or multi-tenant deployment you still want more: run the execution
step in a separate process with OS-level resource limits, connect databases with
read-only credentials, and add a real rate limiter. None of that is included
here because it depends entirely on where you deploy.

## Reporting

If you find a way through the guardrails, please open a GitHub issue with a
minimal reproduction (or email the maintainer if the repo lists one). Include
the generated code that got through and what it managed to do.