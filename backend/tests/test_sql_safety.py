"""SQL guardrail tests: only read-only, single-statement queries get through."""
from __future__ import annotations

import pytest

from app.hooks import SafetyError, validate_sql


def test_valid_select_passes_and_gets_limit():
    sql = validate_sql("SELECT region, SUM(revenue) FROM data GROUP BY region", max_rows=500)
    assert sql.lower().startswith("select")
    assert "LIMIT 500" in sql


def test_existing_limit_is_preserved():
    sql = validate_sql("SELECT * FROM data LIMIT 10", max_rows=500)
    assert sql.count("LIMIT") == 1
    assert "LIMIT 10" in sql


@pytest.mark.parametrize(
    "sql",
    [
        # a LIMIT inside a subquery doesn't bound the outer query
        "SELECT * FROM (SELECT * FROM data LIMIT 5) t CROSS JOIN data",
        # nor does one in a comment
        "SELECT * FROM data -- limit",
    ],
)
def test_limit_elsewhere_in_the_query_does_not_count(sql):
    assert validate_sql(sql, max_rows=500).rstrip().endswith("LIMIT 500")


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT * FROM data LIMIT 100000", "LIMIT 500"),
        ("SELECT * FROM data LIMIT 100000 OFFSET 10", "LIMIT 500 OFFSET 10"),
        ("SELECT * FROM data LIMIT 10, 100000", "LIMIT 10, 500"),
    ],
)
def test_a_limit_above_the_cap_is_clamped(sql, expected):
    assert validate_sql(sql, max_rows=500).endswith(expected)


def test_with_cte_is_allowed():
    sql = validate_sql(
        "WITH r AS (SELECT region, revenue FROM data) SELECT region, SUM(revenue) FROM r GROUP BY region",
        max_rows=100,
    )
    assert sql.lower().startswith("with")


@pytest.mark.parametrize(
    "bad",
    [
        "DROP TABLE data",
        "DELETE FROM data",
        "UPDATE data SET revenue = 0",
        "INSERT INTO data VALUES (1)",
        "CREATE TABLE x (a int)",
        "PRAGMA table_info(data)",
        "ATTACH DATABASE 'x' AS y",
    ],
)
def test_write_and_admin_statements_are_blocked(bad):
    with pytest.raises(SafetyError):
        validate_sql(bad, max_rows=100)


def test_multiple_statements_are_blocked():
    with pytest.raises(SafetyError):
        validate_sql("SELECT 1; DELETE FROM data", max_rows=100)


def test_forbidden_keyword_inside_select_is_blocked():
    with pytest.raises(SafetyError):
        validate_sql("SELECT * FROM data WHERE 1=1 UNION SELECT * INTO evil FROM data", max_rows=100)


def test_column_names_containing_keywords_are_not_false_positives():
    # 'discount' contains 'count'; 'created_at' would contain 'create' only as a
    # substring -- the token-level check must not trip on either.
    sql = validate_sql("SELECT discount, COUNT(*) FROM data GROUP BY discount", max_rows=100)
    assert "discount" in sql.lower()


def test_empty_statement_is_blocked():
    with pytest.raises(SafetyError):
        validate_sql("   ;  ", max_rows=100)
