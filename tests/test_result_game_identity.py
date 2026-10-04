"""非 LOL 清理必须先确认目标身份；异常来源不删除已有业务出场。"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.models.match import Match
from app.models.player import Player
from app.models.sync import SyncTask
from app.models.team import Team
from app.services.ingestion import InvalidResult, NonLOLResult, ingest_result, normalize_result


@pytest.fixture
def payload():
    path = Path(__file__).parent / 'fixtures/scoregg_result_66845.json'
    return json.loads(path.read_text(encoding='utf-8'))


def seed_existing_business(db, *, source='legacy', verified=False):
    date = datetime(2022, 1, 23, 16)
    db.session.add(Match(match_id=66845, source=source, verified=verified, series_id=15481,
                         tournament_id=244, tournament_name='原赛事', date=date, date_source='schedule',
                         red_team_name='T1', blue_team_name='LSB', win_team_name='T1', game_time=2050))
    for team_name, result in (('T1', 1), ('LSB', 0)):
        db.session.add(Team(match_id=66845, team_name=team_name, date=date, result=result,
                            game_time=2050, kill=15, attack=80000, money=50000))
        for position in 'abcde':
            db.session.add(Player(match_id=66845, team_name=team_name, position=position,
                                  name=f'{team_name}-{position}', date=date, result=str(result),
                                  game_time=2050, kills=3, atk=16000, part=60.0))
    db.session.commit()


def business_snapshot(db, match_id=None):
    snapshot = {}
    for model in (Match, Team, Player):
        query = db.session.query(model).order_by(model.id)
        if match_id is not None:
            query = query.filter_by(match_id=match_id)
        snapshot[model.__tablename__] = [
            tuple(getattr(row, column.name) for column in model.__table__.columns) for row in query
        ]
    return snapshot


@pytest.mark.parametrize('declared_id', ['99999', '0', '', None, True, 66845.0, '６６８４５'])
def test_wrong_or_invalid_response_id_cannot_delete_legacy(db, payload, declared_id):
    seed_existing_business(db)
    before = business_snapshot(db)
    payload['data']['gameID'] = '2'
    payload['data']['resultID'] = declared_id
    outcome = ingest_result(payload, 66845)
    assert outcome.status == 'failed'
    assert 'resultID' in outcome.error
    assert business_snapshot(db) == before
    task = db.session.query(SyncTask).one()
    assert task.status == 'failed' and task.attempts == task.failure_count == 1
    assert task.next_retry_at is not None


@pytest.mark.parametrize('game_id', [None, '', ' ', 'invalid', 0, '0', -1, '-1', True, False,
                                     1.0, 2.0, '2.0', '２', {}, []])
def test_unknown_or_invalid_game_id_preserves_legacy_and_all_appearances(db, payload, game_id):
    seed_existing_business(db)
    before = business_snapshot(db)
    payload['data']['gameID'] = game_id
    payload['data']['resultID'] = '66845'
    outcome = ingest_result(payload, 66845)
    assert outcome.status == 'failed'
    assert 'gameID' in outcome.error
    assert business_snapshot(db) == before
    task = db.session.query(SyncTask).one()
    assert task.status == 'failed' and task.attempts == task.failure_count == 1


def test_missing_game_id_preserves_legacy(db, payload):
    seed_existing_business(db)
    before = business_snapshot(db)
    del payload['data']['gameID']
    assert ingest_result(payload, 66845).status == 'failed'
    assert business_snapshot(db) == before


@pytest.mark.parametrize('include_result_id', [False, True])
def test_explicit_game2_only_removes_target_unverified_legacy(db, payload, include_result_id):
    seed_existing_business(db)
    db.session.add(Match(match_id=66846, source='legacy', verified=False, tournament_name='保留对照'))
    db.session.add(Team(match_id=66846, team_name='对照队', kill=9))
    db.session.add(Player(match_id=66846, team_name='对照队', position='a', name='对照选手', kills=9))
    db.session.commit()
    control = business_snapshot(db, match_id=66846)
    payload['data']['gameID'] = '2'
    if include_result_id:
        payload['data']['resultID'] = '66845'
    else:
        assert 'resultID' not in payload['data']  # 真实其它游戏响应可没有这个键。
    assert ingest_result(payload, 66845).status == 'skipped'
    assert all(db.session.query(model).filter_by(match_id=66845).count() == 0 for model in (Match, Team, Player))
    assert business_snapshot(db, match_id=66846) == control
    task = db.session.query(SyncTask).one()
    assert task.result_id == 66845 and task.status == 'skipped' and task.failure_count == 0


@pytest.mark.parametrize('source', ['legacy', 'scoregg', 'scoregg_metadata'])
def test_explicit_game2_cannot_delete_verified_records(db, payload, source):
    seed_existing_business(db, source=source, verified=True)
    before = business_snapshot(db)
    payload['data']['resultID'] = '66845'
    payload['data']['gameID'] = '2'
    assert ingest_result(payload, 66845).status == 'skipped'
    assert business_snapshot(db) == before


@pytest.mark.parametrize('requested_id', [None, '', 0, -1, True, 66845.0])
def test_invalid_requested_id_is_rejected_before_non_lol(payload, requested_id):
    payload['data']['gameID'] = '2'
    with pytest.raises(InvalidResult, match='result_id') as error:
        normalize_result(payload, requested_id)
    assert not isinstance(error.value, NonLOLResult)


def test_missing_response_id_and_whitespace_positive_game_id_keep_lol_contract(payload):
    assert 'resultID' not in payload['data']
    payload['data']['gameID'] = ' 1 '
    assert normalize_result(payload, '66845')['matches'][0]['match_id'] == 66845
    payload['data']['resultID'] = ' 66845 '
    assert normalize_result(payload, 66845)['matches'][0]['match_id'] == 66845
