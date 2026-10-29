import time

import pytest
from fastapi.testclient import TestClient

from enterprise.api import create_app
from enterprise.runtime import Runtime


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.setenv('LLM_MODEL', '')
    with TestClient(create_app(lambda: Runtime(state_dir=tmp_path))) as value:
        yield value


def test_ai_requires_actual_configuration(client):
    response = client.post('/api/queries', json={'question':'退款率是多少', 'mode':'ai'})
    assert response.status_code == 503
    assert client.get('/api/queries').json() == []


def test_unknown_cases_and_external_origins_rejected(client):
    assert client.post('/api/queries', json={'question':'demo','mode':'demo','case_id':'unknown'}).status_code == 422
    assert client.post('/api/queries', headers={'Origin':'https://unrelated.example'}, json={'question':'x'}).status_code == 403
    assert client.get('/api/queries/missing').status_code == 404


@pytest.mark.integration
def test_demo_runs_database_and_exports_report_and_events(client):
    assert client.get('/api/health').json()['database']['read_only_role']
    response = client.post('/api/queries', json={'question':'ignored','mode':'demo','case_id':'refund-trend'})
    assert response.status_code == 202
    job_id = response.json()['id']
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f'/api/queries/{job_id}').json()
        if job['status'] in {'error','complete'}:
            break
        time.sleep(0.05)
    assert job['status'] == 'complete', job
    assert job['result']['row_count'] == 12
    assert len(job['result']['charts']) == 2
    assert job['result']['anomalies'][0]['dimension'] == '华北事业部'
    report = client.get(f'/api/queries/{job_id}/report')
    assert report.status_code == 200
    assert '固定案例 SQL' in report.text and 'sales.order_metrics' in report.text
    events = client.get(f'/api/queries/{job_id}/events').text
    assert 'event: finished' in events and '固定 SQL 案例' in events
