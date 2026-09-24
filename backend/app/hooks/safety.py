"""Guardrails for model-generated code.

Running SQL and Python that an LLM wrote is the scary part of this app, so
everything passes through here first. validate_sql only lets single-statement
SELECT/WITH queries through; validate_python walks the AST and throws out
imports, private and dunder attributes, frame introspection, the dangerous
builtins, and the pandas/numpy calls that reach the filesystem -- all before
anything executes. The sandbox adds a runtime layer on top (see sandbox.py).

Honest caveat: this keeps a local single-user tool safe, it is not a jail.
For untrusted multi-tenant use you'd add OS-level isolation on top. There's a
longer note in the README under "Security model".
"""
from __future__ import annotations

import ast
import re

import sqlparse

# --------------------------------------------------------------------------- SQL

# "replace" isn't here: it's also the everyday REPLACE() string function, and
# the REPLACE INTO statement is still caught by "into".
_FORBIDDEN_SQL = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "attach", "detach", "pragma", "grant", "revoke", "vacuum",
    "reindex", "exec", "execute", "call", "merge", "copy", "into",
}

_TRAILING_LIMIT = re.compile(
    r"\blimit\s+(\d+)(?:\s*,\s*(\d+))?(?:\s+offset\s+\d+)?\s*$", re.IGNORECASE
)


class SafetyError(Exception):
    """Raised when generated code fails a guardrail."""


def _without_string_values(statement) -> str:
    """The query in lower case with its '...' values dropped, for the keyword check.

    WHERE status = 'update pending' is data, not an UPDATE. Only literals with
    no backslash are dropped: sqlparse reads \\' as an escape, Postgres and
    SQLite don't, so a literal containing one could end earlier in the database
    than in sqlparse and hide real SQL. Those stay in and get checked.
    """
    return "".join(
        "''" if token.ttype in sqlparse.tokens.String.Single and "\\" not in token.value
        else token.value
        for token in statement.flatten()
    ).lower()


def validate_sql(sql: str, max_rows: int) -> str:
    """Return a cleaned, row-limited query, or raise SafetyError trying."""
    # Comments out first: "-- no limit" would otherwise count as a LIMIT below.
    sql = sqlparse.format(sql, strip_comments=True).strip().rstrip(";").strip()
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
    tokens = set(re.findall(r"[a-zA-Z_]+", _without_string_values(statements[0])))
    banned = tokens & _FORBIDDEN_SQL
    if banned:
        raise SafetyError(f"Query contains forbidden keyword(s): {', '.join(sorted(banned))}.")

    # Cap the result set. Only a trailing LIMIT bounds the query -- one inside a
    # subquery doesn't -- and a limit the model chose can be bigger than the
    # cap, so it gets clamped rather than trusted.
    match = _TRAILING_LIMIT.search(sql)
    if match is None:
        return f"{sql}\nLIMIT {max_rows}"
    count = 2 if match.group(2) else 1  # MySQL/SQLite "LIMIT offset, count"
    if int(match.group(count)) > max_rows:
        sql = sql[: match.start(count)] + str(max_rows) + sql[match.end(count):]
    return sql


# ------------------------------------------------------------------------ Python

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
    "read_gbq", "ExcelWriter", "ExcelFile", "HDFStore",
    # numpy file access
    "fromfile", "fromregex", "tofile", "dump", "save", "savez", "savez_compressed",
    "savetxt", "load", "loadtxt", "genfromtxt", "memmap",
    # matplotlib: writing to disk (the sandbox encodes the figure itself),
    # importing arbitrary modules as "backends", reading rc files, and pause(),
    # which sleeps in C where the watchdog can't reach it
    "savefig", "imsave", "imread", "print_figure", "backend_registry",
    "load_backend_module", "switch_backend", "rc_context", "pause",
    # expression evaluation back doors. query() belongs here too: pandas
    # evaluates the string itself, attribute access and all, where the AST
    # walk below never sees it.
    "eval", "exec", "query", "system", "popen",
}


# pandas also calls methods by name: df.apply("to_pickle", path=...) is a file
# write with no attribute node in sight. Names worth dispatching to that way
# are rejected as string literals too.
def _dispatchable(name: str) -> bool:
    return name.startswith("__") or (
        name in _FORBIDDEN_ATTRIBUTES and name.startswith(("to_", "read_", "query", "eval"))
    )


# Frame and code objects. A generator's gi_frame leads to f_back, and f_back
# leads to a frame whose f_globals holds the real builtins -- a complete way out
# of the sandbox namespace without a single dunder in sight.
_INTROSPECTION_ATTRIBUTES = {
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await",
    "ag_frame", "ag_code", "ag_await", "tb_frame", "tb_next",
    "f_back", "f_globals", "f_locals", "f_builtins", "f_code",
}


class _Guard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        self.errors.append("`import` statements are not allowed.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.errors.append("`import` statements are not allowed.")

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # Single underscore too: private attributes are never needed for
        # analysis, and the sandbox's module views keep the real module on one.
        if node.attr.startswith("_"):
            self.errors.append(f"Access to private attribute `{node.attr}` is not allowed.")
        elif node.attr in _INTROSPECTION_ATTRIBUTES:
            self.errors.append(f"`{node.attr}` reaches interpreter internals and is not allowed.")
        elif node.attr in _FORBIDDEN_ATTRIBUTES or node.attr.startswith(("read_", "print_")):
            self.errors.append(
                f"`{node.attr}` touches files or evaluates code, which analysis code doesn't need."
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, str) and _dispatchable(node.value):
            self.errors.append(f"The string `{node.value}` names a method that is not allowed.")

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
