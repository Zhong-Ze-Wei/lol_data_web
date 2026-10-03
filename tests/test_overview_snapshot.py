"""总览和历史覆盖在同一响应中沿用同一数据库读取快照。"""

import sqlite3
from datetime import date, datetime

import pytest
from sqlalchemy import event

from app import create_app, db
from app.models import Match, Player, Team
from app.models.sync import HistorySeries, HistoryStage, HistoryTournament, SyncTask


def test_stats_keeps_existing_all_matches_and_distinct_name_semantics(client, db):
    db.session.add_all([
        Match(match_id=1001, verified=True), Match(match_id=1002, verified=False),
        Player(match_id=1001, name='Alice', team_name='A', position='a'),
        Player(match_id=1002, name='Alice', team_name='A', position='a'),
        Player(match_id=1001, name='', team_name='A', position='b'),
        Player(match_id=1001, name=None, team_name='A', position='c'),
        Team(match_id=1001, team_name='A'), Team(match_id=1002, team_name='A'),
        Team(match_id=1001, team_name=''), Team(match_id=1001, team_name=None),
    ])
    db.session.commit()
    assert client.get('/api/stats').json == {
        'status': 'success', 'stats': {'matches': 2, 'verified_matches': 1, 'players': 2, 'teams': 2},
    }
    history = client.get('/api/sync/history').json
    assert history['overview_stats'] == client.get('/api/stats').json['stats']
    assert history['counts']['results'].get('verified', 0) == 0


@pytest.fixture
def overview_snapshot_app(tmp_path):
    database = tmp_path / 'overview.sqlite'
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database.as_posix()}',
                      'DATA_DIR': tmp_path, 'AI_API_KEY': '', 'AUTO_CREATE_DB': False})
    with app.app_context():
        db.create_all()
        db.session.add(HistoryTournament(tournament_id=344, name='Source event',
                                         start_date=date(2019, 1, 1), status='discovered'))
        db.session.flush()
        stage = HistoryStage(tournament_id=344, cache_key='2465', parent_round_id=786, status='discovered')
        db.session.add(stage)
        db.session.flush()
        db.session.add_all([
            HistorySeries(series_id=700, tournament_id=344, stage_id=stage.id,
                          scheduled_at=datetime(2019, 1, 1), status='discovered'),
            SyncTask(task_key='result:1001', result_id=1001, series_id=700, status='imported'),
            Match(match_id=1001, series_id=700, verified=True),
            Match(match_id=1002, verified=True),  # 未绑定目录赛程，仍计入全库总览。
            Match(match_id=1003, verified=False),
            Player(match_id=1001, name='Alice', team_name='A', position='a'),
            Player(match_id=1001, name='Bob', team_name='B', position='a'),
            Team(match_id=1001, team_name='A'), Team(match_id=1001, team_name='B'),
        ])
        db.session.commit()
        engine = db.engine
    yield app, database, engine
    with app.app_context():
        db.session.remove()
        engine.dispose()


def test_history_overview_and_catalog_share_snapshot_during_actual_writer_commit(overview_snapshot_app):
    app, database, engine = overview_snapshot_app
    seen = []

    def import_after_match_counts(connection, cursor, statement, parameters, context, executemany):
        if seen or 'count(distinct(players.name))' not in statement:
            return
        seen.append(connection.connection.driver_connection.in_transaction)
        with sqlite3.connect(database, timeout=.5) as writer:
            writer.execute("INSERT INTO matches (match_id,series_id,source,verified) VALUES (1004,700,'scoregg',1)")
            writer.execute("INSERT INTO sync_tasks (task_key,result_id,series_id,status,attempts,failure_count,created_at,updated_at) "
                           "VALUES ('result:1004',1004,700,'imported',0,0,'2026-10-04','2026-10-04')")
            writer.execute("INSERT INTO players (match_id,name,team_name,position) VALUES (1004,'Carol','C','a')")
            writer.execute("INSERT INTO teams (match_id,team_name) VALUES (1004,'C')")

    event.listen(engine, 'before_cursor_execute', import_after_match_counts)
    try:
        first = app.test_client().get('/api/sync/history').json
    finally:
        event.remove(engine, 'before_cursor_execute', import_after_match_counts)
    assert seen == [True]  # 另一真实 SQLite WAL 连接提交，当前响应仍沿用旧快照。
    assert first['overview_stats'] == {'matches': 3, 'verified_matches': 2, 'players': 2, 'teams': 2}
    assert first['counts']['results']['verified'] == 1 <= first['overview_stats']['verified_matches']
    second = app.test_client().get('/api/sync/history').json
    assert second['overview_stats'] == {'matches': 4, 'verified_matches': 3, 'players': 3, 'teams': 3}
    assert second['counts']['results']['verified'] == 2 <= second['overview_stats']['verified_matches']


def test_empty_overview_keeps_zero_counts(client):
    assert client.get('/api/stats').json['stats'] == {
        'matches': 0, 'verified_matches': 0, 'players': 0, 'teams': 0,
    }
    assert client.get('/api/sync/history').json['overview_stats'] == client.get('/api/stats').json['stats']
