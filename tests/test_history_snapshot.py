"""历史状态 HTTP 响应在后台提交期间保持一个 SQLite 读取快照。"""

import sqlite3
from datetime import date, datetime

import pytest
from sqlalchemy import event

from app import create_app, db
from app.models.sync import HistoryStage, HistoryTournament, SyncRun
from app.routes import sync


@pytest.fixture
def snapshot_app(tmp_path):
    database = tmp_path / 'snapshot.sqlite'
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database.as_posix()}',
                      'DATA_DIR': tmp_path, 'AI_API_KEY': '', 'AUTO_CREATE_DB': False})
    with app.app_context():
        db.create_all()
        db.session.add(HistoryTournament(tournament_id=344, name='Source event',
                                         start_date=date(2019, 1, 1), status='discovered'))
        db.session.flush()
        db.session.add_all([
            HistoryStage(tournament_id=344, cache_key='2465', parent_round_id=786,
                         status='failed', failure_count=5),
            HistoryStage(tournament_id=344, cache_key='2466', parent_round_id=786, status='queued'),
            SyncRun(command='history', status='running', started_at=datetime(2026, 10, 4)),
        ])
        db.session.commit()
        engine = db.engine
    yield app, database, engine
    with app.app_context():
        db.session.remove()
        engine.dispose()


def fail_queued_stage(database):
    with sqlite3.connect(database, timeout=.5) as writer:
        writer.execute("UPDATE history_stages SET status='failed',failure_count=5 WHERE cache_key='2466'")


def assert_failed_snapshot(report, failed):
    assert report['failed_tasks'] == report['counts']['stages']['failed'] == failed
    assert sum(row['failed_tasks'] for row in report['years']) == failed
    assert report['years'][0]['year'] == '2019'
    assert report['exhausted_tasks'] == failed
    assert report['ready_tasks'] == 2 - failed
    assert report['has_runnable_work'] is (failed == 1)
    assert report['counts']['stages']['total'] == 2
    assert report['snapshot_completed'] is False and report['complete_available'] is False


def test_history_response_keeps_counts_years_retry_evidence_and_last_run_in_one_snapshot(snapshot_app):
    app, database, engine = snapshot_app
    seen = []

    def commit_after_stage_counts(connection, cursor, statement, parameters, context, executemany):
        if seen or 'JOIN history_stages' not in statement or 'history_stages.status' not in statement:
            return
        seen.append(connection.connection.driver_connection.in_transaction)
        with sqlite3.connect(database, timeout=.5) as writer:
            writer.execute("UPDATE history_stages SET status='failed',failure_count=5 WHERE cache_key='2466'")
            writer.execute("UPDATE sync_runs SET status='completed' WHERE id=1")
            writer.execute("INSERT INTO sync_runs (run_id,command,status,started_at,request_count,imported,skipped,failed) "
                           "VALUES ('next-run','history','completed','2026-10-04 00:01:00',0,0,0,0)")

    event.listen(engine, 'before_cursor_execute', commit_after_stage_counts)
    try:
        first = app.test_client().get('/api/sync/history').json
    finally:
        event.remove(engine, 'before_cursor_execute', commit_after_stage_counts)
    assert seen == [True]  # 独立 WAL 写连接实际提交成功，读连接仍维持此前快照。
    assert_failed_snapshot(first, 1)
    assert first['last_run']['id'] == 1 and first['last_run']['status'] == 'running'
    second = app.test_client().get('/api/sync/history').json
    assert_failed_snapshot(second, 2)
    assert second['last_run']['run_id'] == 'next-run' and second['last_run']['status'] == 'completed'


@pytest.mark.parametrize('raise_during_report', [False, True])
def test_owned_read_transaction_is_released_at_request_teardown(snapshot_app, monkeypatch, raise_during_report):
    app, database, engine = snapshot_app
    checked_in = []

    def check_transaction(raw, record):
        checked_in.append(raw.in_transaction)

    if raise_during_report:
        def fail_report():
            raise ValueError('isolated report failure')
        monkeypatch.setattr(sync, 'coverage_report', fail_report)
    event.listen(engine, 'checkin', check_transaction)
    try:
        if raise_during_report:
            with pytest.raises(ValueError, match='isolated report failure'):
                app.test_client().get('/api/sync/history')
        else:
            assert app.test_client().get('/api/sync/history').status_code == 200
    finally:
        event.remove(engine, 'checkin', check_transaction)
    assert checked_in == [False]
    fail_queued_stage(database)
    with sqlite3.connect(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM history_stages WHERE status='failed'").fetchone()[0] == 2


def test_history_response_preserves_caller_existing_read_transaction(snapshot_app):
    app, database, _ = snapshot_app
    with app.app_context():
        connection = db.session.connection()
        connection.exec_driver_sql('BEGIN')
        assert db.session.query(HistoryStage).filter_by(status='failed').count() == 1
        fail_queued_stage(database)
        assert_failed_snapshot(app.test_client().get('/api/sync/history').json, 1)
        assert connection.connection.driver_connection.in_transaction is True
        db.session.rollback()
        assert_failed_snapshot(app.test_client().get('/api/sync/history').json, 2)


def test_history_response_does_not_commit_or_rollback_caller_uncommitted_write(snapshot_app):
    app, database, _ = snapshot_app
    with app.app_context():
        stage = db.session.query(HistoryStage).filter_by(cache_key='2466').one()
        stage.status, stage.failure_count = 'failed', 5
        db.session.flush()
        raw = db.session.connection().connection.driver_connection
        changes = raw.total_changes
        assert_failed_snapshot(app.test_client().get('/api/sync/history').json, 2)
        assert raw.in_transaction is True and raw.total_changes == changes
        with sqlite3.connect(database) as reader:
            assert reader.execute("SELECT status FROM history_stages WHERE cache_key='2466'").fetchone()[0] == 'queued'
        db.session.rollback()
        assert_failed_snapshot(app.test_client().get('/api/sync/history').json, 1)


def test_history_response_does_not_flush_caller_pending_changes(snapshot_app):
    app, database, _ = snapshot_app
    with app.app_context():
        stage = db.session.query(HistoryStage).filter_by(cache_key='2466').one()
        stage.status, stage.failure_count = 'failed', 5
        raw = db.session.connection().connection.driver_connection
        changes = raw.total_changes
        assert_failed_snapshot(app.test_client().get('/api/sync/history').json, 1)
        assert stage in db.session.dirty and stage.status == 'failed'
        assert raw.total_changes == changes
        with sqlite3.connect(database) as reader:
            assert reader.execute("SELECT status FROM history_stages WHERE cache_key='2466'").fetchone()[0] == 'queued'
        db.session.rollback()
