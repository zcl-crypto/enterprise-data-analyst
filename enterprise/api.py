"""Local FastAPI application: upstream graph, persisted jobs, SSE and reports."""
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from decimal import Decimal
from threading import BoundedSemaphore, Lock

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from enterprise.analysis import analyze, markdown_report
from enterprise.business import CASES, SCHEMA, TERMS
from enterprise.runtime import ROOT, Runtime
from enterprise.store import JobStore

STAGES = {
    'information_extraction': '解析业务问题与指标口径', 'table_selection': '检索相关表结构',
    'generate_sql': '生成查询 SQL', 'execute_sql': '校验并执行只读查询',
    'regenerate_sql': '根据错误修正 SQL', 'score_sql': '检查查询结果',
    'confidence_gate': '完成查询检查', 'generate_visualization': '生成可视化配置',
    'search_knowledge': '查阅业务定义', 'ask_human': '等待补充信息',
}


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: str = 'ai'
    case_id: str | None = None


class ClarificationRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


def create_app(runtime_factory=Runtime):
    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = runtime_factory()
        app.state.store = JobStore(app.state.runtime.state_dir / 'jobs.db')
        app.state.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='analyst')
        app.state.capacity = BoundedSemaphore(4)
        app.state.submit_lock = Lock()
        yield
        app.state.pool.shutdown(wait=True, cancel_futures=False)
        app.state.runtime.close()

    app = FastAPI(title='企业智能数据分析', version='0.1.0', lifespan=lifespan)

    @app.middleware('http')
    async def restrict_browser_origin(request: Request, call_next):
        # Local single-user app: prevent cross-origin sites from submitting jobs.
        origin = request.headers.get('origin')
        if request.method in {'POST', 'PUT', 'DELETE'} and origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return PlainTextResponse('Cross-origin requests are not allowed', status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def get_job(job_id):
        job = app.state.store.get(job_id)
        if not job:
            raise HTTPException(404, '分析任务不存在')
        return job

    def worker(job_id, case_id=None, answer=None):
        runtime, store = app.state.runtime, app.state.store
        job = store.get(job_id)
        store.update(job_id, status='running', error=None, clarification=None)
        try:
            database = runtime.database_status()
            if job['mode'] == 'demo':
                from openchatbi.text2sql.readonly import execute_readonly
                sql = CASES[case_id]['sql']
                store.event(job_id, {'type': 'stage', 'label': '运行固定 SQL 案例（未调用模型）'})
                columns, rows, truncated = execute_readonly(runtime.engine, sql, SCHEMA,
                                                           max_rows=runtime.max_rows, timeout_ms=runtime.timeout_ms)
                frame = pd.DataFrame(rows, columns=columns)
                for column in frame:
                    if not frame.empty and isinstance(frame[column].iloc[0], Decimal):
                        frame[column] = frame[column].astype(float)
                result = analyze(frame.to_csv(index=False), sql=sql, question=job['question'], truncated=truncated)
            else:
                from langgraph.types import Command
                from openchatbi.constants import SQL_SUCCESS
                options = {'configurable': {'thread_id': job_id}, 'recursion_limit': 30}
                inputs = Command(resume=answer) if answer is not None else {
                    'messages': [('user', job['question'])], 'visualize': True}
                for update in runtime.graph.stream(inputs, options, stream_mode='updates'):
                    if '__interrupt__' in update:
                        clarification = update['__interrupt__'][0].value
                        store.update(job_id, status='needs_input', clarification=clarification)
                        store.event(job_id, {'type': 'clarification', 'value': clarification})
                        return
                    for node, value in update.items():
                        event = {'type': 'stage', 'node': node, 'label': STAGES.get(node, node)}
                        if isinstance(value, dict) and value.get('sql'):
                            event['sql'] = value['sql']
                        store.event(job_id, event)
                state = runtime.graph.get_state(options).values
                if state.get('sql_execution_result') != SQL_SUCCESS:
                    errors = state.get('previous_sql_errors', [])
                    detail = errors[-1]['error'] if errors else '未获得可执行查询，请补充指标、维度或时间范围。'
                    store.update(job_id, status='error', error=detail, sql=state.get('sql', ''))
                    store.event(job_id, {'type': 'error', 'message': detail})
                    return
                result = analyze(state.get('data', ''), sql=state.get('sql', ''), question=job['question'],
                                 truncated=state.get('schema_info', {}).get('truncated', False),
                                 dsl=state.get('visualization_dsl'))
                result['selected_tables'] = state.get('tables', [])
                result['retry_count'] = state.get('sql_retry_count', 0)
            result['as_of'] = database['as_of']
            result['mode'] = job['mode']
            store.event(job_id, {'type': 'stage', 'label': '分析结果并生成 ECharts 图表'})
            store.update(job_id, status='complete', result=result)
            store.event(job_id, {'type': 'complete'})
        except Exception as exc:
            logging.getLogger(__name__).exception('Analysis job %s failed', job_id)
            message = f'分析未完成（{type(exc).__name__}）。请检查数据库、模型配置和服务日志后重试。'
            store.update(job_id, status='error', error=message)
            store.event(job_id, {'type': 'error', 'message': message})
        finally:
            app.state.capacity.release()

    @app.get('/api/health')
    def health():
        runtime = app.state.runtime
        try:
            db = runtime.database_status()
        except Exception:
            db = {'connected': False, 'message': '数据库未连接或查询账号权限不符合要求'}
        return {'database': db, 'model_ready': runtime.model_ready, 'model': runtime.model_name,
                'max_rows': runtime.max_rows, 'timeout_ms': runtime.timeout_ms,
                'data_notice': TERMS['数据性质']}

    @app.get('/api/catalog')
    def catalog():
        return {'definitions': TERMS, 'schema': SCHEMA,
                'cases': [{'id': key, 'question': case['question']} for key, case in CASES.items()]}

    @app.post('/api/queries', status_code=202)
    def query(payload: QueryRequest):
        question = payload.question.strip()
        if not question:
            raise HTTPException(422, '请输入分析问题')
        if payload.mode not in {'ai', 'demo'}:
            raise HTTPException(422, 'mode 必须是 ai 或 demo')
        if payload.mode == 'demo':
            if payload.case_id not in CASES:
                raise HTTPException(422, '请选择有效的固定演示案例')
            question = CASES[payload.case_id]['question']
        elif not app.state.runtime.model_ready:
            raise HTTPException(503, 'AI 问数尚未配置：请在 .env 填写 LLM_API_KEY、LLM_MODEL 和 LLM_BASE_URL 后重启服务。')
        if not app.state.capacity.acquire(blocking=False):
            raise HTTPException(429, '当前任务较多，请稍后再试')
        job = app.state.store.create(question, payload.mode)
        app.state.pool.submit(worker, job['id'], payload.case_id)
        return job

    @app.get('/api/queries')
    def history():
        return [{k: job[k] for k in ['id', 'question', 'mode', 'status', 'created_at']}
                for job in app.state.store.list()]

    @app.get('/api/queries/{job_id}')
    def result(job_id: str):
        job = get_job(job_id)
        job['events'] = app.state.store.events(job_id)
        return job

    @app.post('/api/queries/{job_id}/resume', status_code=202)
    def resume(job_id: str, payload: ClarificationRequest):
        with app.state.submit_lock:
            job = get_job(job_id)
            if job['status'] != 'needs_input':
                raise HTTPException(409, '该任务当前不需要补充信息')
            if not app.state.runtime.model_ready:
                raise HTTPException(503, '请先配置模型')
            if not payload.answer.strip():
                raise HTTPException(422, '补充信息不能为空')
            if not app.state.capacity.acquire(blocking=False):
                raise HTTPException(429, '当前任务较多，请稍后再试')
            app.state.store.update(job_id, status='queued')
            app.state.pool.submit(worker, job_id, answer=payload.answer.strip())
            return {'id': job_id, 'status': 'queued'}

    @app.get('/api/queries/{job_id}/events')
    async def events(job_id: str, request: Request):
        get_job(job_id)
        async def stream():
            last = 0
            while not await request.is_disconnected():
                for event in app.state.store.events(job_id, last):
                    last = event['id']
                    yield f'id: {last}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
                job = app.state.store.get(job_id)
                if job['status'] in {'complete', 'error', 'needs_input'}:
                    yield 'event: finished\ndata: {}\n\n'
                    return
                yield ': heartbeat\n\n'
                await asyncio.sleep(0.4)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})

    @app.get('/api/queries/{job_id}/report')
    def report(job_id: str):
        job = get_job(job_id)
        if job['status'] != 'complete':
            raise HTTPException(409, '分析完成后才能导出报告')
        content = markdown_report(job['result']) + f"\n\n执行方式：{'固定案例 SQL' if job['mode']=='demo' else 'AI 自然语言问数'}\n数据截至：{job['result']['as_of']}\n"
        return PlainTextResponse(content, media_type='text/markdown', headers={
            'Content-Disposition': f'attachment; filename="analysis-{job_id[:8]}.md"'})

    frontend = ROOT / 'frontend' / 'dist'
    if frontend.exists():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
    return app


app = create_app()
