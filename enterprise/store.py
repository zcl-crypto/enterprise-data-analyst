"""Small durable local job/event store. Each request owns a separate graph thread."""
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


class JobStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_job_id ON events(job_id,id);
            ''')
        for job in self.list():
            if job['status'] in {'queued', 'running'}:
                self.update(job['id'], status='error', error='服务重启导致执行中断，请重新提交。')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def create(self, question, mode):
        job = {'id': uuid4().hex, 'question': question, 'mode': mode, 'status': 'queued',
               'created_at': datetime.now(timezone.utc).isoformat(), 'result': None}
        with self.connect() as conn:
            conn.execute('INSERT INTO jobs VALUES (?,?)', (job['id'], json.dumps(job, ensure_ascii=False)))
        return job

    def get(self, job_id):
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self):
        with self.connect() as conn:
            rows = conn.execute('SELECT payload FROM jobs ORDER BY rowid DESC LIMIT 100').fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, job_id, **changes):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            job = json.loads(conn.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()[0])
            job.update(changes)
            conn.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))
        return job

    def event(self, job_id, event):
        with self.connect() as conn:
            conn.execute('INSERT INTO events(job_id,payload) VALUES (?,?)', (job_id, json.dumps(event, ensure_ascii=False)))

    def events(self, job_id, after=0):
        with self.connect() as conn:
            rows = conn.execute('SELECT id,payload FROM events WHERE job_id=? AND id>? ORDER BY id', (job_id, after)).fetchall()
        return [{'id': row[0], **json.loads(row[1])} for row in rows]
