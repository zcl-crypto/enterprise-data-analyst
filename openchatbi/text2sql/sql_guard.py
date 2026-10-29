"""Conservative AST policy for the enterprise PostgreSQL query endpoint.

The policy is deliberately restricted to analytical SELECTs and known built-ins.
It complements, rather than replaces, a non-owner read-only database account.
"""
from collections.abc import Mapping

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope

from openchatbi.text2sql.errors import SQLSecurityError, SQLSyntaxError

SAFE_FUNCTIONS = frozenset('''
AND OR NOT ABS AVG SUM MIN MAX COUNT ROUND FLOOR CEIL CEILING POWER SQRT MOD
COALESCE NULLIF CASE IF CAST TRY_CAST EXTRACT DATE_TRUNC TIMESTAMP_TRUNC
CURRENT_DATE CURRENT_TIMESTAMP CURRENT_TIME DATE DATE_ADD DATE_SUB DATE_DIFF
TO_CHAR TO_DATE TO_TIMESTAMP TIME_TO_STR STR_TO_TIME STR_TO_DATE
LOWER UPPER LENGTH CHAR_LENGTH SUBSTRING TRIM LTRIM RTRIM CONCAT CONCAT_WS
REPLACE SPLIT_PART STR_POSITION POSITION LEFT RIGHT
LAG LEAD ROW_NUMBER RANK DENSE_RANK FIRST_VALUE LAST_VALUE NTILE
STDDEV STDDEV_POP STDDEV_SAMP VARIANCE VAR_POP VAR_SAMP
BOOL_AND BOOL_OR GREATEST LEAST PERCENTILE_CONT PERCENTILE_DISC
ARRAY_AGG STRING_AGG GROUP_CONCAT DATE_PART INTERVAL
'''.split())
FORBIDDEN_NODES = frozenset('''
Insert Update Delete Create Drop Alter Merge Command Copy Into Lock Transaction
Grant Revoke Execute Pragma Use Set Attach Detach Analyze Vacuum TruncateTable
'''.split())


def validate_analytical_sql(sql: str, schema: Mapping[str, Mapping[str, str]], dialect='postgres') -> str:
    """Return normalized SQL or raise a structured, non-executing policy error.

schema is an explicit access policy, e.g. {'sales.orders': {'order_id':'INT'}}.
CTE aliases are resolved by scopes so a CTE cannot conceal an unauthorized table.
Column resolution is performed on a copy; original joins and output labels are retained.
"""
    if not schema:
        raise SQLSecurityError('No authorized tables configured')
    if not sql.strip() or len(sql) > 50000:
        raise SQLSecurityError('Empty or oversized query')
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError as exc:
        raise SQLSyntaxError(f'Invalid SQL syntax: {exc}') from exc
    if len(statements) != 1:
        raise SQLSecurityError('Only one SELECT statement is allowed')
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLSecurityError('Only analytical SELECT queries are allowed')
    nodes = list(tree.walk())
    if len(nodes) > 5000:
        raise SQLSecurityError('Query is too complex')
    for node in nodes:
        if type(node).__name__ in FORBIDDEN_NODES:
            raise SQLSecurityError(f'Operation not allowed: {type(node).__name__}')
        if isinstance(node, exp.With) and node.args.get('recursive'):
            raise SQLSecurityError('Recursive queries are not permitted')
        if isinstance(node, exp.Func):
            if isinstance(node.parent, exp.Dot):
                raise SQLSecurityError('Qualified function calls are not permitted')
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name().upper()
            if name not in SAFE_FUNCTIONS:
                raise SQLSecurityError(f'Function not allowed: {name}')

    policy = {name.lower(): dict(columns) for name, columns in schema.items()}
    short_names: dict[str, list[str]] = {}
    for name in policy:
        short_names.setdefault(name.split('.')[-1], []).append(name)
    physical_tables = []
    for scope in traverse_scope(tree):
        for _, source in scope.selected_sources.values():
            if isinstance(source, Scope):
                continue
            if not isinstance(source, exp.Table) or not isinstance(source.this, exp.Identifier):
                raise SQLSecurityError('Table-valued functions are not permitted')
            if source.catalog:
                raise SQLSecurityError('Cross-database access is not permitted')
            name = f'{source.db}.{source.name}'.lower() if source.db else source.name.lower()
            if not source.db:
                matches = short_names.get(name, [])
                name = matches[0] if len(matches) == 1 else name
            if name not in policy:
                raise SQLSecurityError(f'Table not authorized: {source.sql()}')
            physical_tables.append((source, name))
    if not physical_tables:
        raise SQLSecurityError('Query must read an authorized business table')

    # qualify() validates a copy against the permitted fields, while execution
    # keeps the original projection. A physical-table * would otherwise expose
    # columns omitted from that policy (including fields added after deployment).
    # Make the model enumerate its columns; COUNT(*) remains a row count.
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise SQLSyntaxError('Use explicit column names instead of projection wildcards')

    # Resolve unqualified names to the authorized schema before executing.
    for table, name in physical_tables:
        if '.' in name:
            namespace, table_name = name.rsplit('.', 1)
            table.set('db', exp.to_identifier(namespace))
            table.set('this', exp.to_identifier(table_name))

    check_tree = tree.copy()
    for table in check_tree.find_all(exp.Table):
        table.set('db', None)
        table.set('catalog', None)
    for column in check_tree.find_all(exp.Column):
        column.set('db', None)
        column.set('catalog', None)
    flat_schema = {name.split('.')[-1]: columns for name, columns in policy.items()}
    try:
        qualify(check_tree, dialect=dialect, schema=flat_schema, validate_qualify_columns=True)
    except OptimizeError as exc:
        raise SQLSyntaxError(f'Column or alias resolution failed: {exc}') from exc
    return tree.sql(dialect=dialect)
