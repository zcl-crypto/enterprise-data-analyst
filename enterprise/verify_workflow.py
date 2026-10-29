"""Deterministic integration audit: only LLM responses are scripted; graph and DB are real.

This is a test entry point, never used by the application. It does not measure LLM accuracy.
"""
import json
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from enterprise.business import CASES
from enterprise.runtime import ROOT, Runtime


class ScriptedModel(BaseChatModel):
    responses: list = Field(default_factory=list)
    calls: int = 0

    @property
    def _llm_type(self):
        return 'integration-test-only'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.calls >= len(self.responses):
            raise AssertionError('Graph made an unexpected extra LLM call')
        response = self.responses[self.calls]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=response if isinstance(response, AIMessage) else AIMessage(content=response))])


EXTRACTION = json.dumps({'rewrite_question': CASES['refund-trend']['question'],
    'keywords': ['department_name', 'ordered_at', 'is_refunded', 'paid_amount'],
    'dimensions': ['department_name', 'ordered_at'], 'metrics': ['is_refunded'],
    'start_time': None, 'end_time': None})
TABLES = json.dumps({'tables': [{'table': 'sales.order_metrics', 'columns': ['department_name','ordered_at','is_refunded','status']}]})


def main():
    good_sql = CASES['refund-trend']['sql']
    bad_sql = 'SELECT nonexistent FROM sales.order_metrics'
    model = ScriptedModel(responses=[EXTRACTION, TABLES, bad_sql, good_sql])
    runtime = Runtime(llm=model, state_dir=ROOT / '.runtime' / 'workflow-audit')
    from openchatbi.constants import SQL_SUCCESS, SQL_SECURITY_ERROR
    from langgraph.types import Command
    try:
        runtime.database_status()
        def run(responses):
            model.responses = responses
            model.calls = 0
            options = {'configurable': {'thread_id': uuid4().hex}, 'recursion_limit': 30}
            events = list(runtime.graph.stream({'messages': [('user', CASES['refund-trend']['question'])],
                                              'visualize': True}, options, stream_mode='updates'))
            return runtime.graph.get_state(options).values, events, options

        state, events, _ = run([EXTRACTION, TABLES, bad_sql, good_sql])
        assert state['sql_execution_result'] == SQL_SUCCESS, state
        assert state['sql_retry_count'] == 1
        assert state['schema_info']['row_count'] == 12
        assert any('table_selection' in item for item in events)
        assert any('regenerate_sql' in item for item in events)

        state, _, _ = run([EXTRACTION, TABLES, 'SELECT * FROM sales.order_metrics', good_sql])
        assert state['sql_execution_result'] == SQL_SUCCESS
        assert state['sql_retry_count'] == 1
        assert 'explicit column' in state['previous_sql_errors'][0]['error']

        state, _, _ = run([EXTRACTION, TABLES, bad_sql, bad_sql, bad_sql])
        assert state['sql_execution_result'] != SQL_SUCCESS
        assert state['sql_retry_count'] == 2 and model.calls == 5

        state, _, _ = run([EXTRACTION, TABLES, 'DELETE FROM sales.orders'])
        assert state['sql_execution_result'] == SQL_SECURITY_ERROR
        assert state['sql_retry_count'] == 0 and model.calls == 3

        ask = AIMessage(content='', tool_calls=[{'id':'clarify-1','name':'AskHuman','args':{'question':'请确认使用订单退款率还是退款金额率？'}}])
        _, events, options = run([ask])
        assert any('__interrupt__' in item for item in events)
        model.responses = [EXTRACTION, TABLES, good_sql]
        model.calls = 0
        list(runtime.graph.stream(Command(resume='订单退款率'), options, stream_mode='updates'))
        assert runtime.graph.get_state(options).values['sql_execution_result'] == SQL_SUCCESS
        report = {'passed': True, 'llm_mode': 'scripted test fixture; not a live model',
                  'verified': ['upstream schema retrieval', 'SQLGlot validation', 'PostgreSQL execution',
                    'one-step correction', 'projection wildcard correction', 'two-retry cap',
                    'unsafe SQL abort', 'checkpoint clarification/resume']}
        (ROOT / '.runtime' / 'workflow-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
