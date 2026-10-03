import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.models.match import Match
from app.models.sync import SyncRun, SyncTask


def write_worker(app, **changes):
    state = {'status': 'running', 'running': True, 'heartbeat_at': datetime.now(timezone.utc).isoformat(),
             'current_batch': 38, 'last_completed_batch': 37, **changes}
    path = app.config['DATA_DIR'] / 'history-worker.json'
    path.write_text(json.dumps(state), encoding='utf-8')
    return path


def test_status_includes_live_worker_without_changing_batch_or_data_contract(app, client, db):
    db.session.add(SyncRun(command='history', status='budget_exhausted', request_count=400,
                           finished_at=datetime(2026, 10, 3, 21, 38)))
    db.session.add(Match(match_id=34, source='scoregg', verified=True,
                         date=datetime(2016, 10, 15), date_source='schedule'))
    db.session.add(SyncTask(task_key='result:34', result_id=34, status='imported'))
    db.session.commit()
    write_worker(app)
    response = client.get('/api/sync/status')
    assert response.status_code == 200
    data = response.get_json()
    assert data['last_run']['status'] == 'budget_exhausted' and data['last_run']['request_count'] == 400
    assert data['history_worker']['alive'] is True and data['history_worker']['heartbeat_state'] == 'fresh'
    assert data['history_worker']['current_batch'] == 38 and data['history_worker']['last_completed_batch'] == 37
    assert data['tasks'] == {'imported': 1} and data['verified_matches'] == 1
    assert data['data_range']['min_date'] == '2016-10-15T00:00:00'
    assert data['date_quality']['confirmed'] == 1 and 'schedule' in data and 'record_range' in data


@pytest.mark.parametrize('phase,alive', [
    ('running', True), ('continue', True), ('daily_pause', True), ('locked', True),
    ('retry_later', True), ('retry_wait', True), ('stopped', False), ('completed', False), ('failed', False),
])
def test_status_preserves_runtime_wait_or_terminal_phase_and_alive_evidence(app, client, phase, alive):
    write_worker(app, status=phase)
    worker = client.get('/api/sync/status').get_json()['history_worker']
    assert worker['status'] == phase and worker['alive'] is alive


@pytest.mark.parametrize('offset,state', [(-91, 'expired'), (30, 'future')])
def test_old_running_record_cannot_override_invalid_heartbeat(app, client, db, offset, state):
    db.session.add(SyncRun(command='history', status='running'))
    db.session.commit()
    write_worker(app, heartbeat_at=(datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat())
    data = client.get('/api/sync/status').get_json()
    assert data['last_run']['status'] == 'running'
    assert data['history_worker']['alive'] is False and data['history_worker']['heartbeat_state'] == state


def test_missing_worker_does_not_infer_running_from_a_database_run(client, db):
    db.session.add(SyncRun(command='history', status='running'))
    db.session.commit()
    data = client.get('/api/sync/status').get_json()
    assert data['last_run']['status'] == 'running' and data['history_worker'] is None


def test_invalid_runtime_is_reported_without_forwarding_process_or_secret_fields(app, client):
    path = write_worker(app, pid=12345, api_key='not-a-real-key', provider={'headers': {'secret': 'not-a-real-secret'}})
    data = client.get('/api/sync/status').get_json()
    assert data['history_worker']['alive'] is True
    assert 'pid' not in data['history_worker'] and 'api_key' not in data['history_worker']
    assert 'provider' not in data['history_worker'] and 'not-a-real-key' not in json.dumps(data)
    path.write_text('{', encoding='utf-8')
    assert client.get('/api/sync/status').get_json()['history_worker'] == {'alive': False, 'heartbeat_state': 'invalid'}


def test_status_is_readonly_and_does_not_rewrite_runtime_file(app, client, db):
    db.session.add(SyncRun(command='history', status='running'))
    db.session.commit()
    path = write_worker(app)
    original = path.read_bytes()
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(db.engine, 'before_cursor_execute', capture)
    try:
        assert client.get('/api/sync/status').status_code == 200
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture)
    assert not set(statements) & {'INSERT', 'UPDATE', 'DELETE', 'ALTER', 'CREATE', 'DROP', 'REPLACE'}
    assert path.read_bytes() == original
    assert db.session.query(SyncRun).one().status == 'running'
