import os
from decimal import Decimal
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from enterprise.business import CASES, SCHEMA
from openchatbi.text2sql.readonly import execute_readonly


@pytest.fixture(scope='module')
def engine():
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    url = os.getenv('DATABASE_URL')
    if not url:
        pytest.skip('Set DATABASE_URL to run PostgreSQL integration tests')
    value = create_engine(url)
    yield value
    value.dispose()


@pytest.mark.integration
def test_refund_cohort_counts_do_not_double_count_split_refunds(engine):
    columns, rows, truncated = execute_readonly(engine, CASES['refund-trend']['sql'], SCHEMA)
    assert len(rows) == 12 and not truncated
    records = [dict(zip(columns, row)) for row in rows]
    north = [row for row in records if row['department_name'] == '华北事业部']
    assert len(north) == 3
    assert all(row['order_count'] == 95 and row['refunded_orders'] == 29 for row in north)
    assert all(row['refund_rate'] == Decimal('30.53') for row in north)


@pytest.mark.integration
def test_result_limit_marks_truncation(engine):
    columns, rows, truncated = execute_readonly(engine, 'SELECT order_id FROM sales.orders ORDER BY order_id', SCHEMA, max_rows=3)
    assert columns == ['order_id'] and len(rows) == 3 and truncated


@pytest.mark.integration
def test_database_role_rejects_writes_even_without_ast_guard(engine):
    with engine.connect() as conn:
        assert conn.execute(text('SHOW transaction_read_only')).scalar() == 'on'
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE sales.orders SET paid_amount=0"))
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.exec_driver_sql('SET TRANSACTION READ WRITE')
            conn.execute(text("UPDATE sales.orders SET paid_amount=0"))


@pytest.mark.integration
def test_server_timeout_cancels_expensive_select(engine):
    query = 'SELECT SUM(a.paid_amount*b.paid_amount*c.paid_amount) FROM sales.orders a CROSS JOIN sales.orders b CROSS JOIN sales.orders c'
    with pytest.raises(DBAPIError, match='statement timeout'):
        execute_readonly(engine, query, SCHEMA, timeout_ms=100)
