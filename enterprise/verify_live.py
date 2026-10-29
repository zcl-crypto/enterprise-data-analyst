"""Run three real model queries and compare results with reviewed SQL.

Requires explicitly configured credentials. This script uses the model API and
may incur provider charges; it never fabricates responses or falls back to demo SQL.
"""
import json
from io import StringIO
from uuid import uuid4

import pandas as pd

from enterprise.business import CASES, SCHEMA
from enterprise.runtime import ROOT, Runtime


def main():
    runtime = Runtime()
    try:
        if not runtime.model_ready:
            raise SystemExit('模型未配置：填写 .env 的 LLM_API_KEY、LLM_MODEL、LLM_BASE_URL 后再运行。')
        from openchatbi.constants import SQL_SUCCESS
        from openchatbi.text2sql.readonly import execute_readonly
        runtime.database_status()
        results = []
        for key, case in CASES.items():
            options = {'configurable': {'thread_id': 'live-' + uuid4().hex}, 'recursion_limit': 30}
            state = {}
            try:
                runtime.graph.invoke({'messages': [('user', case['question'])], 'visualize': True}, options)
                snapshot = runtime.graph.get_state(options)
                state = snapshot.values
                if snapshot.next:
                    raise AssertionError('模型请求澄清，需要在界面中确认口径后再验收')
                if state.get('sql_execution_result') != SQL_SUCCESS:
                    raise AssertionError('模型查询未执行成功')
                columns, rows, truncated = execute_readonly(runtime.engine, case['sql'], SCHEMA)
                expected = pd.DataFrame(rows, columns=columns)
                actual = pd.read_csv(StringIO(state['data']))
                assert not truncated and not state.get('schema_info', {}).get('truncated')
                assert set(actual.columns) == set(expected.columns), '结果列与标准口径不一致'
                for frame in (actual, expected):
                    for column in frame:
                        if column not in {'month', 'department_name', 'reason'}:
                            frame[column] = pd.to_numeric(frame[column])
                order = [c for c in ['month','department_name','reason'] if c in expected]
                if order:
                    expected = expected.sort_values(order).reset_index(drop=True)
                    actual = actual.sort_values(order).reset_index(drop=True)
                pd.testing.assert_frame_equal(actual[columns], expected, check_dtype=False, atol=0.01, rtol=0.0001)
                results.append({'case': key, 'passed': True, 'sql': state['sql'], 'rows': len(actual)})
            except Exception as exc:
                failure = {'case': key, 'passed': False, 'error_type': type(exc).__name__,
                           'thread_id': options['configurable']['thread_id'], 'sql': state.get('sql', '')}
                if isinstance(exc, AssertionError):
                    failure['comparison_error'] = str(exc)[:2000]
                results.append(failure)
        report = {'model': runtime.model_name, 'llm_mode': 'live API', 'cases': results,
                  'passed': all(case['passed'] for case in results)}
        (ROOT / '.runtime' / 'live-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report['passed']:
            raise SystemExit(1)
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
