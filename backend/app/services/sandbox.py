"""Runs the (already validated) generated snippets.

The namespace is built from scratch: the code sees df, pd, np, plt when
charting, a ~20-function builtins allow-list, and nothing else. stdout gets
captured. Snippets are expected to leave their output in a variable called
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
import sys
import threading
import time
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
        with _time_limit(settings.sandbox_timeout_seconds), redirect_stdout(buffer):
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
        "pd": pd,
        "np": np,
        "result": None,
        "__builtins__": _SAFE_BUILTINS,
    }

    if not with_plot:
        stdout = _execute(code, namespace)
        return SandboxResult(result=namespace.get("result"), stdout=stdout)

    namespace["plt"] = plt
    with _PLOT_LOCK:
        plt.close("all")
        try:
            stdout = _execute(code, namespace)
            figure = plt.gcf()
            png = _encode(figure) if figure.get_axes() else None
            return SandboxResult(result=figure, stdout=stdout, figure_png=png)
        finally:
            plt.close("all")  # never leave figures parked in the global registry
