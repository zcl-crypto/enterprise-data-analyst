import pytest

from enterprise.business import CASES, SCHEMA
from openchatbi.text2sql.errors import SQLSecurityError, SQLSyntaxError
from openchatbi.text2sql.sql_guard import validate_analytical_sql


@pytest.mark.parametrize('case', CASES.values())
def test_business_queries_allowed(case):
    assert 'sales.' in validate_analytical_sql(case['sql'], SCHEMA)


@pytest.mark.parametrize('sql', [
    'DELETE FROM sales.orders',
    'SELECT * FROM sales.orders; DROP TABLE sales.orders',
    'WITH d AS (DELETE FROM sales.orders RETURNING *) SELECT * FROM d',
    'SELECT * INTO backup FROM sales.orders',
    'SELECT * FROM sales.orders FOR UPDATE',
    "SELECT pg_sleep(2) FROM sales.orders",
    "SELECT pg_read_file('/etc/passwd') FROM sales.orders",
    "SELECT set_config('statement_timeout','0',false) FROM sales.orders",
    'SELECT * FROM pg_catalog.pg_authid',
    'WITH x AS (SELECT * FROM secret.orders) SELECT * FROM x',
    'SELECT * FROM generate_series(1,1000000000)',
    "SELECT custom_function(order_id) FROM sales.orders",
    'WITH RECURSIVE t AS (SELECT 1 UNION ALL SELECT * FROM t) SELECT * FROM t',
])
def test_forbidden_queries_rejected(sql):
    with pytest.raises(SQLSecurityError):
        validate_analytical_sql(sql, SCHEMA)


def test_unknown_columns_are_repairable():
    with pytest.raises(SQLSyntaxError):
        validate_analytical_sql('SELECT nonexistent FROM sales.orders', SCHEMA)


def test_cte_resolution_and_explicit_namespace():
    sql = validate_analytical_sql('WITH x AS (SELECT order_id FROM orders) SELECT COUNT(*) FROM x', SCHEMA)
    assert 'sales.orders' in sql


def test_literal_keywords_and_comments_do_not_change_policy():
    assert validate_analytical_sql("SELECT 'DELETE FROM x' AS label, order_id FROM sales.orders -- safe", SCHEMA)


def test_no_policy_is_fail_closed():
    with pytest.raises(SQLSecurityError):
        validate_analytical_sql('SELECT * FROM orders', {})


@pytest.mark.parametrize('sql', [
    'SELECT * FROM sales.orders',
    'SELECT o.* FROM sales.orders o',
    'WITH x AS (SELECT * FROM sales.orders) SELECT order_id FROM x',
    'SELECT ARRAY_AGG(o.*) FROM sales.orders o',
])
def test_projection_wildcards_cannot_bypass_column_policy(sql):
    # The physical table has paid_amount, customer_id, etc.; this policy exposes only order_id.
    with pytest.raises(SQLSyntaxError, match='explicit column'):
        validate_analytical_sql(sql, {'sales.orders': {'order_id': 'INT'}})


def test_explicit_columns_enforce_policy_without_disabling_count_star():
    policy = {'sales.orders': {'order_id': 'INT'}}
    assert validate_analytical_sql('SELECT order_id FROM sales.orders', policy)
    assert validate_analytical_sql('SELECT COUNT(*) FROM sales.orders', policy)
    with pytest.raises(SQLSyntaxError):
        validate_analytical_sql('SELECT paid_amount FROM sales.orders', policy)
