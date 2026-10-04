"""身份投影来自28972/28973原件；数值沿用公开66845 fixture，不冒充真实两局指标。"""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app import create_app, db as database
from app.models.match import Match
from app.models.player import Player
from app.models.sync import SyncTask
from app.models.team import Team
from app.services.ingestion import InvalidResult, PendingResult, ingest_result, normalize_result, start_task


REAL_DETAIL_IDENTITY = {
    28972: {'sha256': '7924c0b228179e5e8882a08288358da2375962aa7939f34783a49647a2b50ee0',
            'game_time_m': '32', 'game_time_s': '23'},
    28973: {'sha256': '6990f68a23befee26ca0430e33555449955d75d7b9b9c2a4ccc97878f7956c0f',
            'game_time_m': '25', 'game_time_s': '9'},
}


@pytest.fixture
def app(tmp_path):
    """真实临时SQLite文件，显式URI覆盖默认生产配置。"""
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{(tmp_path / "binding.db").as_posix()}',
                      'DATA_DIR': tmp_path, 'AI_API_KEY': '', 'AUTO_CREATE_DB': True})
    with app.app_context():
        yield app
        database.session.remove()
        database.drop_all()


@pytest.fixture
def payload():
    body = json.loads((Path(__file__).parent / 'fixtures/scoregg_result_66845.json').read_text('utf-8'))
    body['data']['result_list'].update(red_teamID='17', blue_teamID='1', teamID_a='17', teamID_b='1',
                                       win_teamID='17', red_result='1', blue_result='0')
    return body


@pytest.fixture
def schedule(payload):
    info = payload['data']['result_list']
    return {'series_id': 58146, 'tournament_id': 1007, 'tournament_name': 'LPL',
            'scheduled_at': datetime(2026, 7, 22, 17),
            'source_row': {'matchID': '58146', 'teamID_a': '17', 'teamID_b': '1',
                           'team_short_name_a': info['red_name'], 'team_short_name_b': info['blue_name']}}


def historical_projection(payload, result_id):
    body = copy.deepcopy(payload)
    data = body['data']; info = data['result_list']
    for key in ('max_mvp', 'max_beiguo'):
        data[key]['match_id'] = '15481'
    data['max_mvp']['teamID'] = '7'
    data['max_beiguo']['teamID'] = '208'
    info.update(red_name='T1', blue_name='LSB', red_teamID='7', blue_teamID='208',
                teamID_a='208', teamID_b='7', win_teamID='7', red_result='1', blue_result='0',
                game_time_m=REAL_DETAIL_IDENTITY[result_id]['game_time_m'],
                game_time_s=REAL_DETAIL_IDENTITY[result_id]['game_time_s'])
    good = {'series_id': 15481, 'tournament_id': 244, 'tournament_name': '2022 LCK春季赛',
            'scheduled_at': datetime(2022, 1, 23, 16),
            'source_row': {'matchID': '15481', 'match_date': '2022-01-23', 'match_time': '16:00',
                           'teamID_a': '208', 'teamID_b': '7', 'team_short_name_a': 'LSB',
                           'team_short_name_b': 'T1', 'team_a_win': '0', 'team_b_win': '2'}}
    bad = {'series_id': 15481, 'tournament_id': 403, 'tournament_name': '2017 LCL 夏季赛',
           'scheduled_at': datetime(2017, 7, 22, 21),
           'source_row': {'matchID': '15481', 'match_date': '2017-07-22', 'match_time': '21:00',
                          'teamID_a': '1987', 'teamID_b': '200', 'team_short_name_a': 'TJ',
                          'team_short_name_b': 'Gambit', 'team_a_win': '0', 'team_b_win': '1'}}
    return body, good, bad


@pytest.mark.parametrize('result_id', [28972, 28973])
def test_real_15481_identity_rejects_old_claim_and_accepts_2022(payload, result_id):
    body, good, bad = historical_projection(payload, result_id)
    with pytest.raises(InvalidResult, match='身份'):
        normalize_result(body, result_id, bad, allow_incomplete=True)
    normalized = normalize_result(body, result_id, good)
    assert normalized['matches'][0]['tournament_id'] == 244
    assert normalized['matches'][0]['date'] == datetime(2022, 1, 23, 16)
    assert normalized['matches'][0]['team_name_provenance']['selected_source'] == 'schedule'


@pytest.mark.parametrize('detail_known,schedule_known', [(True, True), (True, False), (False, True)])
def test_row_bo_conflict_is_rejected_even_when_team_fields_are_missing(payload, schedule, detail_known, schedule_known):
    schedule['source_row'].update(matchID='99999', teamID_a=None, teamID_b=None)
    if not detail_known:
        for key in ('max_mvp', 'max_beiguo'):
            payload['data'][key].pop('match_id')
    if not schedule_known:
        schedule.pop('series_id')
    with pytest.raises(InvalidResult, match='BO'):
        normalize_result(payload, 66845, schedule)


@pytest.mark.parametrize('case', ['different_pair', 'duplicate_row_pair', 'duplicate_detail_pair',
                                   'row_partial_outside_detail', 'detail_partial_outside_row',
                                   'aux_partial_outside', 'aux_duplicate_pair'])
def test_explicit_team_conflicts_are_rejected(payload, schedule, case):
    info = payload['data']['result_list']; row = schedule['source_row']
    if case == 'different_pair':
        row.update(teamID_a='1987', teamID_b='200')
    elif case == 'duplicate_row_pair':
        row.update(teamID_a='17', teamID_b='17')
    elif case == 'duplicate_detail_pair':
        info.update(blue_teamID='17')
    elif case == 'row_partial_outside_detail':
        row.update(teamID_a='1987', teamID_b=None)
    elif case == 'detail_partial_outside_row':
        row.update(teamID_a='1987', teamID_b='200')
        info.update(blue_teamID=None)
    elif case == 'aux_partial_outside':
        info.update(teamID_a='1987', teamID_b=None)
    else:
        info.update(teamID_a='17', teamID_b='17')
    with pytest.raises(InvalidResult, match='身份'):
        normalize_result(payload, 66845, schedule)


def test_missing_bo_cannot_hide_known_team_conflict(payload, schedule):
    schedule.pop('series_id')
    schedule['source_row'].update(matchID=None, teamID_a='1987', teamID_b='200')
    for key in ('max_mvp', 'max_beiguo'):
        payload['data'][key].pop('match_id')
    with pytest.raises(InvalidResult, match='身份'):
        normalize_result(payload, 66845, schedule)


def test_missing_bo_and_labels_cannot_hide_auxiliary_conflict(payload, schedule):
    schedule['source_row'].update(matchID=None, team_short_name_a=None, team_short_name_b='')
    payload['data']['result_list'].update(teamID_a='999', teamID_b=None)
    with pytest.raises(InvalidResult, match='身份'):
        normalize_result(payload, 66845, schedule)


@pytest.mark.parametrize('unknown', [None, '', 'unknown', 0, -1, '٥٨١٤٦'])
def test_unknown_row_bo_does_not_become_a_conflict(payload, schedule, unknown):
    schedule['source_row']['matchID'] = unknown
    normalized = normalize_result(payload, 66845, schedule)
    assert normalized['matches'][0]['series_id'] == 58146
    assert normalized['matches'][0]['team_name_provenance']['selected_source'] == 'detail'


@pytest.mark.parametrize('case', ['row_partial', 'detail_partial', 'row_unknown', 'labels_missing'])
def test_missing_or_partial_identity_without_known_conflict_keeps_compatibility(payload, schedule, case):
    row = schedule['source_row']; info = payload['data']['result_list']
    if case == 'row_partial':
        row['teamID_b'] = None
    elif case == 'detail_partial':
        info['blue_teamID'] = None
    elif case == 'row_unknown':
        row.update(matchID=None, teamID_a='unknown', teamID_b=0)
    else:
        row.update(team_short_name_a=None, team_short_name_b='')
    normalized = normalize_result(payload, 66845, schedule)
    assert len(normalized['teams']) == 2 and len(normalized['players']) == 10
    assert normalized['matches'][0]['date'] == schedule['scheduled_at']
    assert normalized['matches'][0]['team_name_provenance']['selected_source'] == 'detail'


@pytest.mark.parametrize('row', [None, [], 'unknown'])
def test_no_explicit_row_keeps_legacy_and_retry_behavior(payload, schedule, row):
    schedule['source_row'] = row
    payload['data']['result_list']['teamID_a'] = '1987'
    assert normalize_result(payload, 66845, schedule)['matches'][0]['series_id'] == 58146
    assert normalize_result(payload, 66845)['matches'][0]['series_id'] == 58146


def test_auxiliary_only_valid_bo_is_accepted(payload, schedule):
    payload['data']['max_mvp'].pop('match_id')
    normalized = normalize_result(payload, 66845, schedule)
    assert normalized['matches'][0]['series_id'] == 58146
    assert normalized['matches'][0]['team_name_provenance']['detail']['series_id_source'] == 'max_beiguo.match_id'


def test_strict_placeholder_duration_stays_pending_before_identity_guard(payload, schedule):
    payload['data']['result_list'].update(game_time_m='0', game_time_s='1')
    schedule['source_row'].update(teamID_a='1987', teamID_b='200')
    with pytest.raises(PendingResult, match='00:00 / 00:01'):
        normalize_result(payload, 66845, schedule)


def test_historical_placeholder_does_not_allow_known_wrong_identity(payload, schedule):
    payload['data']['result_list'].update(game_time_m='0', game_time_s='1')
    schedule['source_row'].update(teamID_a='1987', teamID_b='200')
    with pytest.raises(InvalidResult, match='身份'):
        normalize_result(payload, 66845, schedule, allow_incomplete=True)


def test_winner_validation_still_rejects_conflict(payload, schedule):
    payload['data']['result_list']['win_teamID'] = '999'
    with pytest.raises(InvalidResult, match='胜方'):
        normalize_result(payload, 66845, schedule)


def business_snapshot(db):
    return {model.__tablename__: copy.deepcopy([dict(row) for row in db.session.execute(
        select(model.__table__).order_by(model.id)).mappings()]) for model in (Match, Team, Player)}


@pytest.mark.parametrize('result_id', [28972, 28973])
@pytest.mark.parametrize('conflict', ['real_old_claim', 'row_bo', 'auxiliary'])
def test_conflicting_update_preserves_all_business_fields_and_fails_once(db, payload, tmp_path, result_id, conflict):
    body, good, bad = historical_projection(payload, result_id)
    assert ingest_result(body, result_id, good).status == 'imported'
    assert Path(db.engine.url.database).is_file()
    before = business_snapshot(db)
    natural_keys = {'teams': {(row['match_id'], row['team_name']) for row in before['teams']},
                    'players': {(row['match_id'], row['team_name'], row['position']) for row in before['players']}}
    incoming = copy.deepcopy(body)
    attempted = copy.deepcopy(bad if conflict == 'real_old_claim' else good)
    if conflict == 'row_bo':
        attempted['source_row']['matchID'] = '99999'
    elif conflict == 'auxiliary':
        incoming['data']['result_list'].update(teamID_a='1987', teamID_b=None)
    incoming['data']['result_list']['red_star_a_kills'] = '99'
    raw = tmp_path / f'{result_id}.json'
    raw.write_text(json.dumps(incoming, ensure_ascii=False), encoding='utf-8')
    raw_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    task_before = db.session.query(SyncTask).one()
    attempts_before = task_before.attempts
    start_task(result_id, attempted)
    outcome = ingest_result(incoming, result_id, attempted)
    assert outcome.status == 'failed'
    assert business_snapshot(db) == before
    assert natural_keys['teams'] == {(row.match_id, row.team_name) for row in db.session.query(Team)}
    assert natural_keys['players'] == {(row.match_id, row.team_name, row.position) for row in db.session.query(Player)}
    task = db.session.query(SyncTask).one()
    assert task.status == 'failed' and task.failure_count == 1
    assert task.attempts == attempts_before + 1 and task.next_retry_at is not None
    assert '身份' in outcome.error or 'BO' in outcome.error
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == raw_sha
    # Task记录的是本次尝试，get_task/start_task可更新其metadata；业务表保护不扩充成Task保护承诺。
    assert task.scheduled_at == attempted['scheduled_at']


def test_fresh_conflict_creates_only_one_failed_task(db, payload, schedule):
    schedule['source_row']['matchID'] = '99999'
    outcome = ingest_result(payload, 66845, schedule)
    assert outcome.status == 'failed'
    assert business_snapshot(db) == {'matches': [], 'teams': [], 'players': []}
    task = db.session.query(SyncTask).one()
    assert task.status == 'failed' and task.failure_count == task.attempts == 1
