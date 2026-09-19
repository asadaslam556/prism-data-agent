"""Python guardrail + sandbox tests."""
from __future__ import annotations

import pandas as pd
import pytest

from app.hooks import SafetyError, validate_python
from app.services import sandbox

# ------------------------------------------------------------------ AST guardrail

@pytest.mark.parametrize(
    "bad",
    [
        "import os",
        "from os import path",
        "open('/etc/passwd')",
        "__import__('os')",
        "eval('1+1')",
        "exec('x=1')",
        "df.__class__.__mro__",
        "getattr(df, 'to_csv')",
    ],
)
def test_dangerous_code_is_blocked(bad):
    with pytest.raises(SafetyError):
        validate_python(bad)


def test_normal_pandas_code_is_allowed():
    validate_python("result = df.groupby('region')['revenue'].sum().sort_values()")


def test_syntax_errors_raise_safety_error():
    with pytest.raises(SafetyError):
        validate_python("result = df.groupby(")


# ------------------------------------------------------------------------ sandbox

def test_result_variable_is_returned(sample_df):
    out = sandbox.run_analysis("result = df['revenue'].sum()", sample_df)
    assert out.result == 250.0


def test_stdout_is_captured(sample_df):
    out = sandbox.run_analysis("print('rows:', len(df))\nresult = len(df)", sample_df)
    assert "rows: 4" in out.stdout
    assert out.result == 4


def test_original_dataframe_is_not_mutated(sample_df):
    sandbox.run_analysis("df['revenue'] = 0\nresult = df['revenue'].sum()", sample_df)
    assert sample_df["revenue"].sum() == 250.0


def test_blocked_builtins_are_unavailable_at_runtime(sample_df):
    # Even if validation were bypassed, the reduced builtins stop `open` at runtime.
    with pytest.raises(RuntimeError):
        sandbox.run_analysis("result = open('x.txt')", sample_df)


def test_runtime_errors_are_wrapped(sample_df):
    with pytest.raises(RuntimeError) as excinfo:
        sandbox.run_analysis("result = df['missing_column'].sum()", sample_df)
    assert "KeyError" in str(excinfo.value)


def test_plot_mode_returns_a_figure(sample_df):
    code = "df.plot(kind='bar', x='region', y='revenue')\nplt.title('t')"
    out = sandbox.run_analysis(code, sample_df, with_plot=True)
    assert out.result is not None
    assert out.result.get_axes()


# ------------------------------------------------------- filesystem escape route

# pandas and numpy are filesystem libraries, which is easy to forget when the
# guard is busy looking for `open` and `__import__`. `df.to_csv("/etc/cron.d/x")`
# is an ordinary attribute call on a name the snippet is meant to have, and it
# used to sail straight through and write the file.

@pytest.mark.parametrize(
    "code",
    [
        "df.to_csv('/tmp/should_not_exist.csv')",
        "df.to_pickle('/tmp/should_not_exist.pkl')",
        "df.to_html('/tmp/should_not_exist.html')",
        "df.to_excel('/tmp/should_not_exist.xlsx')",
        "result = pd.read_csv('/etc/hostname')",
        "result = pd.read_pickle('/tmp/anything.pkl')",
        "result = np.fromfile('/etc/hostname')",
        "np.save('/tmp/should_not_exist.npy', df.values)",
        "plt.savefig('/tmp/should_not_exist.png')",
        "result = pd.eval('1 + 1')",
    ],
)
def test_filesystem_and_eval_calls_are_blocked(code):
    with pytest.raises(SafetyError):
        validate_python(code)


def test_nothing_slipped_through_to_disk(tmp_path, sample_df):
    """Belt and braces: even if validation were skipped, no file appears."""
    target = tmp_path / "escaped.csv"
    with pytest.raises(SafetyError):
        validate_python(f"df.to_csv('{target}')")
    assert not target.exists()


@pytest.mark.parametrize(
    "code",
    [
        "result = df.groupby('region')['revenue'].sum().to_dict()",
        "result = df.describe().to_string()",
        "result = df['revenue'].to_numpy().mean()",
        "result = df['revenue'].values.std()",
        "result = np.percentile(df['revenue'].values, 90)",
        "result = df.pivot_table(index='region', values='revenue', aggfunc='sum').to_string()",
    ],
)
def test_ordinary_analysis_code_still_passes(code, sample_df):
    """The denylist must not get in the way of the code the agent actually writes."""
    validate_python(code)
    outcome = sandbox.run_analysis(code, sample_df)
    assert outcome.result is not None


# ------------------------------------------------- routes through the libraries

# pandas, numpy and pyplot import os, sys and subprocess at module level, so any
# submodule used to be a way out: pd.io.common.os.remove(...) passed the guard
# and ran. Each of these was a working escape before the module views, the
# private-attribute rule and the audit hook went in.

@pytest.mark.parametrize(
    "code",
    [
        "g = (x for x in [1])\nresult = g.gi_frame.f_back",
        "result = pd._module",
        "result = df.query('@df.sum.__globals__')",
        "df.apply('to_pickle', path='x.pkl')",
        "df.values.dump('x.pkl')",
        "fig = plt.figure()\nfig.canvas.print_png('x.png')",
        "result = plt.backend_registry.load_backend_module('module://os')",
        "result = pd.ExcelFile('/etc/hostname')",
        "plt.pause(10 ** 9)",
    ],
)
def test_library_escape_routes_are_blocked(code):
    with pytest.raises(SafetyError):
        validate_python(code)


@pytest.mark.parametrize(
    "code",
    [
        "result = pd.io.common.os.getcwd()",
        "result = plt.sys.modules['subprocess']",
        "result = np.f2py",
    ],
)
def test_module_views_refuse_submodules(code, sample_df):
    validate_python(code)  # nothing here the AST guard can name
    with pytest.raises(RuntimeError, match="not available"):
        sandbox.run_analysis(code, sample_df, with_plot=True)


def test_module_views_keep_the_numeric_submodules(sample_df):
    code = (
        "rng = np.random.default_rng(0)\n"
        "ok = pd.api.types.is_numeric_dtype(df['revenue'])\n"
        "result = (ok, float(np.linalg.norm([3, 4])), rng.integers(1, 2))"
    )
    validate_python(code)
    assert sandbox.run_analysis(code, sample_df).result == (True, 5.0, 1)


def test_file_writes_are_refused_at_runtime(tmp_path, sample_df):
    """The audit hook catches what the AST guard can't read, like a name built at runtime."""
    target = tmp_path / "x.pkl"
    code = f"df.apply('to_' + 'pickle', path={str(target)!r})"
    validate_python(code)
    with pytest.raises(RuntimeError, match="PermissionError"):
        sandbox.run_analysis(code, sample_df)
    assert not target.exists()


@pytest.mark.parametrize(
    "module",
    ["os", "sys", "subprocess", "importlib", "builtins", "shutil", "socket"],
)
def test_guarded_import_refuses_everything_dangerous(module, sample_df):
    """The sandbox hands out a narrow __import__ so numpy's lazy imports work.

    It must only ever return already-loaded numpy/pandas internals.
    """
    from app.services.sandbox import _guarded_import

    with pytest.raises(ImportError):
        _guarded_import(module)


def test_guarded_import_allows_the_numeric_stack():
    from app.services.sandbox import _guarded_import

    assert _guarded_import("numpy") is not None
    assert _guarded_import("pandas") is not None


# ---------------------------------------------------------------- chart types

# The agent should be able to draw anything a business user asks for. seaborn
# isn't installed (and an import would be rejected anyway), so heatmaps have to
# go through imshow -- the chart prompt spells that out because the model
# otherwise reaches for seaborn, gets blocked, and burns a retry.

CHART_SNIPPETS = {
    "bar": "df.plot(kind='bar', x='region', y='revenue'); plt.title('t')",
    "barh": "df.plot(kind='barh', x='region', y='revenue'); plt.title('t')",
    "line": "plt.plot(df['region'], df['revenue']); plt.title('t')",
    "pie": "plt.pie(df['revenue'], labels=df['region']); plt.title('t')",
    "scatter": "plt.scatter(df['quantity'], df['revenue'], s=df['revenue']); plt.title('t')",
    "histogram": "plt.hist(df['revenue'], bins=3); plt.title('t')",
    "boxplot": "plt.boxplot([df['revenue'], df['quantity']]); plt.title('t')",
    "area": "df.plot(kind='area', x='region', y='revenue'); plt.title('t')",
    "step": "plt.step(df['region'], df['revenue']); plt.title('t')",
    "dual_axis": (
        "fig, ax = plt.subplots()\n"
        "ax.bar(df['region'], df['revenue'])\n"
        "ax2 = ax.twinx()\n"
        "ax2.plot(df['region'], df['quantity'], color='red')\n"
        "ax.set_title('t')"
    ),
    "heatmap": (
        "pivot = df.pivot_table(index='region', columns='region', values='revenue')\n"
        "fig, ax = plt.subplots()\n"
        "im = ax.imshow(pivot.values, cmap='YlGnBu', aspect='auto')\n"
        "plt.colorbar(im, ax=ax)\n"
        "ax.set_title('t')"
    ),
}


@pytest.mark.parametrize("name,code", sorted(CHART_SNIPPETS.items()))
def test_common_chart_types_render(name, code, sample_df):
    validate_python(code)
    outcome = sandbox.run_analysis(code, sample_df, with_plot=True)
    assert outcome.figure_png, f"{name} produced no image"


def test_seaborn_import_is_still_rejected():
    """Not an oversight -- there's no seaborn here, and imports stay blocked."""
    with pytest.raises(SafetyError):
        validate_python("import seaborn as sns\nsns.heatmap(df)")


# ------------------------------------------------------ telling types apart

# The model used to get bare column names, so it couldn't tell which columns it
# could do arithmetic on. It called .mean() on a text column, got
# "TypeError: dtype 'str' does not support operation 'mean'", and burned a
# retry. Sending the type alongside each name is the cheap fix.

def test_column_description_labels_each_type():
    from app.skills.base import describe_columns

    frame = pd.DataFrame({
        "region": ["A", "B"],
        "revenue": [1.5, 2.5],
        "orders": [10, 20],
        "when": pd.to_datetime(["2025-01-01", "2025-02-01"]),
        "flag": [True, False],
    })
    described = describe_columns(frame)

    assert "region (text)" in described
    assert "revenue (number)" in described
    assert "orders (number)" in described
    assert "when (date)" in described
    # bool is numeric as far as pandas is concerned, but averaging flags is
    # rarely what anyone meant, so it gets its own label
    assert "flag (boolean)" in described


def test_the_failing_case_is_recognisable_as_text():
    """The exact shape that broke: a text column the model tried to average."""
    from app.skills.base import describe_columns

    frame = pd.DataFrame({
        "risk_level": ["HIGH_VOLATILITY", "MEDIUM_CONCENTRATION"],
        "avg_discount": [0.07, 0.08],
    })
    described = describe_columns(frame)
    assert "risk_level (text)" in described
    assert "avg_discount (number)" in described
