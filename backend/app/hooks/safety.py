"""Guardrails for model-generated code.

Running SQL and Python that an LLM wrote is the scary part of this app, so
everything passes through here first. validate_sql only lets single-statement
SELECT/WITH queries through; validate_python walks the AST and throws out
imports, dunder tricks, the dangerous builtins, and the pandas/numpy calls that
reach the filesystem -- all before anything executes.

Honest caveat: this keeps a local single-user tool safe, it is not a jail.
For untrusted multi-tenant use you'd add OS-level isolation on top. There's a
longer note in the README under "Security model".
"""
from __future__ import annotations

import ast
import re

import sqlparse

# --------------------------------------------------------------------------- SQL

_FORBIDDEN_SQL = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "replace", "attach", "detach", "pragma", "grant", "revoke", "vacuum",
    "reindex", "exec", "execute", "call", "merge", "copy", "into",
}


class SafetyError(Exception):
    """Raised when generated code fails a guardrail."""


def validate_sql(sql: str, max_rows: int) -> str:
    """Return a cleaned, row-limited query, or raise SafetyError trying."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise SafetyError("Empty SQL statement.")

    statements = [s for s in sqlparse.parse(sql) if str(s).strip()]
    if len(statements) != 1:
        raise SafetyError("Only a single SQL statement is allowed.")

    lowered = sql.lower()
    first = lowered.lstrip("( \n\t")
    if not (first.startswith("select") or first.startswith("with")):
        raise SafetyError("Only SELECT / WITH (read-only) queries are allowed.")

    # token-level on purpose: a substring check would reject the 'discount'
    # column because it contains 'count'. Been there.
    tokens = set(re.findall(r"[a-zA-Z_]+", lowered))
    banned = tokens & _FORBIDDEN_SQL
    if banned:
        raise SafetyError(f"Query contains forbidden keyword(s): {', '.join(sorted(banned))}.")

    # cap the result set if the model forgot to
    if not re.search(r"\blimit\b", lowered):
        sql = f"{sql}\nLIMIT {max_rows}"
    return sql


# ------------------------------------------------------------------------ Python

# Names the generated analysis code is allowed to reference.
_ALLOWED_NAMES = {
    "df", "pd", "np", "plt", "result",
    "True", "False", "None",
    "len", "range", "min", "max", "sum", "abs", "round", "sorted",
    "list", "dict", "set", "tuple", "float", "int", "str", "bool",
    "enumerate", "zip", "print",
}

_FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "__import__", "input",
                    "globals", "locals", "getattr", "setattr", "delattr", "vars"}

# The bit that's easy to miss: pandas and numpy are filesystem libraries. None
# of the checks above touch `df.to_csv("/etc/cron.d/x")` -- it's an ordinary
# attribute call on a name the snippet is supposed to have. So the reader and
# writer methods get named and blocked explicitly. Anything that only moves data
# around in memory (to_dict, to_numpy, to_string, ...) stays allowed, because
# that's most of what real analysis code does.
_FORBIDDEN_ATTRIBUTES = {
    # pandas writers
    "to_csv", "to_pickle", "to_excel", "to_json", "to_html", "to_sql",
    "to_parquet", "to_feather", "to_hdf", "to_stata", "to_clipboard",
    "to_latex", "to_xml", "to_orc", "to_gbq",
    # pandas readers
    "read_csv", "read_pickle", "read_excel", "read_json", "read_html",
    "read_sql", "read_sql_query", "read_sql_table", "read_parquet",
    "read_feather", "read_hdf", "read_stata", "read_orc", "read_sas",
    "read_spss", "read_xml", "read_table", "read_fwf", "read_clipboard",
    "read_gbq", "ExcelWriter", "HDFStore",
    # numpy file access
    "fromfile", "tofile", "save", "savez", "savez_compressed", "savetxt",
    "load", "loadtxt", "genfromtxt", "memmap",
    # matplotlib writing to disk; the sandbox encodes the figure itself
    "savefig", "imsave", "imread",
    # expression evaluation back doors
    "eval", "exec", "system", "popen",
}


class _Guard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        self.errors.append("`import` statements are not allowed.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.errors.append("`import` statements are not allowed.")

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if isinstance(node.attr, str) and node.attr.startswith("__"):
            self.errors.append(f"Access to dunder attribute `{node.attr}` is not allowed.")
        elif node.attr in _FORBIDDEN_ATTRIBUTES:
            self.errors.append(
                f"`{node.attr}` touches files or evaluates code, which analysis code doesn't need."
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id in _FORBIDDEN_CALLS:
            self.errors.append(f"Use of `{node.id}` is not allowed.")
        self.generic_visit(node)


def validate_python(code: str) -> None:
    """Raise SafetyError if the snippet breaks the rules above."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:  # pragma: no cover - surfaced to the agent
        raise SafetyError(f"Generated code has a syntax error: {exc.msg}") from exc

    guard = _Guard()
    guard.visit(tree)
    if guard.errors:
        raise SafetyError(" ".join(dict.fromkeys(guard.errors)))
