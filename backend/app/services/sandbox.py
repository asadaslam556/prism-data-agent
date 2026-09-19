"""Runs the (already validated) generated snippets.

The namespace is built from scratch: the code sees df, module views of pd, np
and plt (charting only) that won't hand out other modules, a ~20-function
builtins allow-list, and nothing else. An audit hook refuses file writes,
processes and sockets while the snippet runs. stdout gets captured. Snippets are expected to leave their output in a variable called
`result` -- that convention is baked into the prompts.

Two things in here exist purely because branches run in parallel now.

pyplot keeps global state, and it is not thread safe. Two branches drawing at
once used to deadlock the whole request -- one figure would come back and the
other threads would hang forever. So the entire plotting section, right through
to encoding the PNG, happens under one lock. Charts take milliseconds and the
model calls around them take seconds, so serialising this costs nothing worth
measuring.

And there is a watchdog. Nothing in the safety guard stops a model from writing
`while True: pass`, and in CPython a tight loop like that doesn't just hang its
own request, it starves every other thread of the GIL. The tracer below checks
the clock on each line and raises once the snippet has outstayed its welcome.
"""
from __future__ import annotations

import base64
import builtins
import io
import os
import sys
import threading
import time
import types
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # no display on a server; set once, not per call
import matplotlib.pyplot as plt  # noqa: E402 - must follow the backend choice

from app.config import settings  # noqa: E402

# the only builtins generated code gets. open/__import__/eval etc. simply
# don't exist in there.
_SAFE_BUILTIN_NAMES = (
    "len", "range", "min", "max", "sum", "abs", "round", "sorted", "list",
    "dict", "set", "tuple", "float", "int", "str", "bool", "enumerate", "zip",
    "print", "isinstance",
)
_SAFE_BUILTINS: dict[str, Any] = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}

# numpy imports lazily partway through some ordinary calls -- df['v'].values.mean()
# is enough to trigger it -- so with no __import__ at all those blow up with a
# confusing KeyError. Rather than hand the snippet the real one, this only ever
# returns modules that are already loaded AND on the list below, which is
# numpy/pandas internals the snippet can already reach through np and pd. Asking
# for os, sys, subprocess or importlib gets nothing.
_IMPORTABLE_ROOTS = ("numpy", "pandas", "math", "statistics", "datetime", "decimal", "dateutil")


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    root = name.split(".")[0]
    if root in _IMPORTABLE_ROOTS and name in sys.modules:
        return sys.modules[name]
    raise ImportError(f"importing {name!r} is not allowed in analysis code")


_SAFE_BUILTINS["__import__"] = _guarded_import

# pandas, numpy and pyplot all import os, sys, subprocess and friends at module
# level, so any submodule is a route out: pd.io.common.os, plt.sys.modules,
# np.f2py.subprocess. A denylist of names can't keep up with that, so the
# snippet never gets the real modules. It gets a view that hands back
# functions, classes and constants as normal but refuses to return a module,
# apart from the handful of numeric submodules below that analysis code uses.
_ALLOWED_SUBMODULES = frozenset({
    "numpy.random", "numpy.linalg", "numpy.fft", "numpy.ma",
    "pandas.api", "pandas.api.types", "pandas.tseries", "pandas.tseries.offsets",
    "matplotlib.cm", "matplotlib.colors", "matplotlib.ticker", "matplotlib.dates",
})


class _ModuleView:
    """Read-only stand-in for a module that won't give up other modules.

    The real module sits on a private attribute, which the AST guard stops
    generated code from reading.
    """

    __slots__ = ("_module",)

    def __init__(self, module: types.ModuleType) -> None:
        object.__setattr__(self, "_module", module)

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._module, name)
        if isinstance(value, types.ModuleType):
            if value.__name__ in _ALLOWED_SUBMODULES:
                return _ModuleView(value)
            raise AttributeError(f"{self._module.__name__}.{name} is not available in analysis code")
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("modules are read-only in analysis code")

    def __repr__(self) -> str:
        return f"<module {self._module.__name__!r}>"


_PD, _NP, _PLT = _ModuleView(pd), _ModuleView(np), _ModuleView(plt)

# The AST guard reads names, so it can't see a method name glued together at
# runtime ("to_" + "pickle"), and a denylist only covers what someone thought
# of. As a backstop, a PEP 578 audit hook refuses the things analysis code never
# needs while a snippet is running on this thread: writing files, starting
# processes, opening sockets, loading native code. Reads stay allowed because
# matplotlib opens its own font files mid-render.
_BLOCKED_EVENT_PREFIXES = (
    "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.kill",
    "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
    "os.truncate", "os.symlink", "os.link", "os.putenv", "os.unsetenv",
    "os.startfile", "os.chdir", "os.utime",
    "subprocess.", "shutil.", "socket.", "ctypes.", "winreg.",
    "urllib.", "http.", "ftplib.", "smtplib.", "webbrowser.",
)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_RUNNING = threading.local()


def _audit(event: str, args: tuple) -> None:
    if not getattr(_RUNNING, "active", False):
        return
    if event == "open":
        flags = args[2] if len(args) > 2 else 0
        if isinstance(flags, int) and flags & _WRITE_FLAGS:
            raise PermissionError(f"writing to {args[0]!r} is not allowed in analysis code")
    elif event.startswith(_BLOCKED_EVENT_PREFIXES):
        raise PermissionError(f"{event} is not allowed in analysis code")


sys.addaudithook(_audit)


@contextmanager
def _audited():
    _RUNNING.active = True
    try:
        yield
    finally:
        _RUNNING.active = False

# everything touching pyplot's global figure registry goes through here
_PLOT_LOCK = threading.RLock()


class SandboxTimeoutError(RuntimeError):
    """The snippet ran longer than sandbox_timeout_seconds and was stopped."""


@dataclass
class SandboxResult:
    result: Any
    stdout: str
    figure_png: str | None = None  # base64 PNG, only when with_plot


@contextmanager
def _time_limit(seconds: float):
    """Stop the snippet if it overruns.

    Works by tracing line events in this thread, which is what makes it usable
    from a worker thread (signal.alarm only fires on the main thread). It can't
    interrupt a single long call down in C -- one enormous allocation will still
    hurt -- but it reliably catches the runaway Python loop, which is the shape
    this actually fails in. SECURITY.md spells out the rest.
    """
    deadline = time.monotonic() + seconds
    previous = sys.gettrace()

    def tracer(frame, event, arg):
        if time.monotonic() > deadline:
            raise SandboxTimeoutError(f"Code ran longer than {seconds:g}s and was stopped.")
        return tracer

    sys.settrace(tracer)
    try:
        yield
    finally:
        sys.settrace(previous)  # hand tracing back (coverage, debuggers)


def _execute(code: str, namespace: dict[str, Any]) -> str:
    buffer = io.StringIO()
    try:
        with _time_limit(settings.sandbox_timeout_seconds), redirect_stdout(buffer), _audited():
            exec(code, namespace)  # noqa: S102 - locked-down namespace, validated upstream
    except SandboxTimeoutError:
        raise
    except Exception as exc:  # goes back to the agent, which can retry or move on
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    return buffer.getvalue()


def _encode(figure) -> str:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def run_analysis(code: str, df: pd.DataFrame, *, with_plot: bool = False) -> SandboxResult:
    """Run `code` against a copy of df; return its result and captured stdout.

    with_plot=True also hands back the finished chart as a base64 PNG in
    `figure_png`. Encoding happens in here rather than in the caller so the
    figure never leaves the lock half-built.
    """
    namespace: dict[str, Any] = {
        "df": df.copy(),
        "pd": _PD,
        "np": _NP,
        "result": None,
        "__builtins__": _SAFE_BUILTINS,
    }

    if not with_plot:
        stdout = _execute(code, namespace)
        return SandboxResult(result=namespace.get("result"), stdout=stdout)

    namespace["plt"] = _PLT
    with _PLOT_LOCK:
        plt.close("all")
        try:
            stdout = _execute(code, namespace)
            figure = plt.gcf()
            png = _encode(figure) if figure.get_axes() else None
            return SandboxResult(result=figure, stdout=stdout, figure_png=png)
        finally:
            plt.close("all")  # never leave figures parked in the global registry
