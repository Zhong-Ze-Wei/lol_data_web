from datetime import date, datetime, timedelta, timezone
import json

from app.models.sync import HistorySeries, HistoryStage, HistoryTournament, SyncRun


def test_empty_inventory_does_not_claim_history_complete(client):
    response = client.get('/api/sync/history')
    assert response.status_code == 200
    assert response.json['counts']['catalog']['total'] == 0
    assert response.json['discovery_complete'] is False
    assert response.json['last_run'] is None
    assert response.json['schedule']['enabled'] is False


def test_unpublished_games_are_visible_separate_from_fetch_failures(client, db):
    db.session.add(HistoryTournament(tournament_id=399, name='未知目录日期', status='discovered'))
    db.session.flush()
    stage = HistoryStage(tournament_id=399, cache_key='p_1', parent_round_id=1, status='discovered')
    db.session.add(stage)
    db.session.flush()
    db.session.add(HistorySeries(series_id=10, tournament_id=399, stage_id=stage.id,
                                 scheduled_at=datetime(2016, 5, 1), source_status='2',
                                 is_publist=0, status='pending'))
    db.session.commit()
    result = client.get('/api/sync/history').json
    assert result['counts']['series']['unpublished'] == 1
    assert result['pending_publication'] == 1
    assert result['failed_tasks'] == 0
    assert any(row['year'] == '2016' and row['series'] == 1 for row in result['years'])
    assert any(row['year'] == 'unknown' and row['tournaments'] == 1 for row in result['years'])


def test_status_combines_durable_inventory_and_last_history_run(client, app, db):
    db.session.add_all([HistoryTournament(tournament_id=333, name='S1', start_date=date(2011, 6, 18)),
                        SyncRun(command='daily', status='completed'),
                        SyncRun(command='history', status='running')])
    db.session.commit()
    (app.config['DATA_DIR'] / 'history-worker.json').write_text(
        json.dumps({'status': 'continue', 'batch': 2}), encoding='utf-8')
    (app.config['DATA_DIR'] / 'history-schedule.json').write_text(
        json.dumps({'enabled': True, 'time': '08:25'}), encoding='utf-8-sig')
    result = client.get('/api/sync/history').json
    assert result['last_run']['command'] == 'history'
    assert result['worker']['batch'] == 2
    assert result['worker']['alive'] is False  # 旧continue及DB running都不是当前心跳证据。
    assert result['schedule']['enabled'] is True
    assert result['counts']['catalog']['queued'] == 1


def test_status_uses_recent_runtime_heartbeat_without_exposing_private_fields_or_mutating_runs(client, app, db):
    run = SyncRun(command='history', status='running')
    db.session.add(run)
    db.session.commit()
    state_file = app.config['DATA_DIR'] / 'history-worker.json'
    state_file.write_text(json.dumps({'status': 'daily_pause', 'running': True,
        'heartbeat_at': datetime.now(timezone.utc).isoformat(), 'batch': 0, 'current_batch': None,
        'pid': 1234, 'api_key': 'private', 'resume_at': '2026-10-04T00:20:00Z'}), encoding='utf-8')
    state = client.get('/api/sync/history').json['worker']
    assert state['alive'] is True and state['status'] == 'daily_pause'
    assert 'pid' not in state and 'api_key' not in state
    assert db.session.get(SyncRun, run.id).status == 'running'
    state_file.write_text(json.dumps({'status': 'continue', 'running': True,
        'heartbeat_at': (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()}), encoding='utf-8')
    expired = client.get('/api/sync/history').json
    assert expired['worker']['alive'] is False and expired['worker']['heartbeat_state'] == 'expired'
    assert expired['last_run']['status'] == 'running'
