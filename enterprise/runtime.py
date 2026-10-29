"""Configure upstream components before importing its module-level retrievers."""
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from enterprise.business import SCHEMA
from enterprise.catalog_builder import CATALOG_PATH, build_catalog

ROOT = Path(__file__).resolve().parents[1]


class Runtime:
    def __init__(self, llm=None, state_dir=None):
        load_dotenv(ROOT / '.env')
        self.state_dir = Path(state_dir or ROOT / '.runtime')
        self.state_dir.mkdir(parents=True, exist_ok=True)
        build_catalog()
        self.model_ready = llm is not None or bool(os.getenv('LLM_API_KEY') and os.getenv('LLM_MODEL'))
        self.model_name = os.getenv('LLM_MODEL', '')
        self.max_rows = max(1, min(int(os.getenv('SQL_MAX_ROWS', '500')), 10000))
        self.timeout_ms = max(100, min(int(os.getenv('SQL_TIMEOUT_MS', '5000')), 30000))
        uri = os.getenv('DATABASE_URL', '')
        if not uri:
            raise RuntimeError('请先执行 python -m enterprise.setup 配置本地数据库。')
        self.engine = create_engine(uri, pool_pre_ping=True, connect_args={'connect_timeout': 5})
        self.graph = None
        self.checkpoint_connection = None
        if self.model_ready:
            self._build_graph(uri, llm)

    def _build_graph(self, uri, llm):
        from openchatbi import config
        if llm is None:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=self.model_name, api_key=os.environ['LLM_API_KEY'],
                             base_url=os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'),
                             temperature=0, timeout=45, max_retries=1)
        config.set({
            'organization': '企业经营分析演示', 'dialect': 'postgres', 'default_llm': llm,
            'catalog_store': {'store_type': 'file_system', 'auto_load': False, 'data_path': str(CATALOG_PATH)},
            'bi_config_file': str(CATALOG_PATH / 'bi.yaml'),
            'data_warehouse_config': {'uri': uri, 'echo': False, 'connect_args': {'connect_timeout': 5}},
            'enable_ast_sql_guard': True, 'sql_access_schema': SCHEMA,
            'sql_timeout_ms': self.timeout_ms, 'sql_result_limit': self.max_rows,
            'sql_max_retries': 2, 'retry_on_timeout': False,
            'extraction_max_tool_rounds': 2, 'visualization_mode': 'rule',
            'python_executor': 'docker', 'enable_confidence_gate': False,
        })
        # Import only after config.set: upstream initializes retrieval stores at module import.
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.store.memory import InMemoryStore
        from openchatbi.text2sql.sql_graph import build_sql_graph
        self.checkpoint_connection = sqlite3.connect(self.state_dir / 'checkpoints.db', check_same_thread=False)
        saver = SqliteSaver(self.checkpoint_connection)
        self.graph = build_sql_graph(config.get().catalog_store, saver, InMemoryStore())
        config.get().catalog_store.get_sql_engine().echo = False

    def database_status(self):
        with self.engine.connect() as conn:
            row = conn.execute(text('SELECT current_user, current_date, (SELECT COUNT(*) FROM sales.orders)')).one()
            role = conn.execute(text('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')).one()
            writable = conn.execute(text("SELECT has_table_privilege(current_user, 'sales.orders', 'INSERT,UPDATE,DELETE')")).scalar()
            if any(role) or writable:
                raise RuntimeError('查询连接必须使用非特权只读账号，请检查 DATABASE_URL。')
            return {'connected': True, 'read_only_role': True, 'as_of': str(row[1]), 'orders': row[2]}

    def close(self):
        self.engine.dispose()
        if self.checkpoint_connection:
            self.checkpoint_connection.close()
