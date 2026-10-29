"""Bounded PostgreSQL execution with transaction-local limits."""
from sqlalchemy import text

from openchatbi.text2sql.errors import SQLSecurityError
from openchatbi.text2sql.sql_guard import validate_analytical_sql


def execute_readonly(engine, sql, schema, *, max_rows=500, timeout_ms=5000):
    if engine.dialect.name != 'postgresql':
        raise SQLSecurityError('Enterprise execution requires PostgreSQL')
    max_rows = max(1, min(int(max_rows), 10000))
    timeout_ms = max(100, min(int(timeout_ms), 30000))
    normalized = validate_analytical_sql(sql, schema)
    # Fetch one sentinel row to distinguish genuinely complete results from truncation.
    bounded = f'SELECT * FROM ({normalized}) AS enterprise_result LIMIT {max_rows + 1}'
    with engine.connect() as conn:
        with conn.begin():
            conn.exec_driver_sql('SET TRANSACTION READ ONLY')
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{timeout_ms}ms'")
            conn.exec_driver_sql("SET LOCAL lock_timeout = '1000ms'")
            conn.exec_driver_sql('SET LOCAL search_path = sales, pg_catalog')
            result = conn.execute(text(bounded))
            columns = list(result.keys())
            rows = result.fetchmany(max_rows + 1)
            result.close()
    return columns, rows[:max_rows], len(rows) > max_rows
