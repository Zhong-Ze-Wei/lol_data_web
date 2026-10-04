"""官网 BO20839 实际 metadata 清单；HTTP 仅用隔离 transport 模拟。"""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
import requests

from app.models.match import Match
from app.models.sync import HistoryTournament, HistoryStage, HistorySeries, SyncTask
from app.services import history, spider
from scripts import pipeline


METADATA_FILE = Path(__file__).parent / 'fixtures' / 'scoregg_bo20839_metadata.json'
# 只投影身份/计数/清单；真实完整 response.body SHA 3913e2c0...389f6，另存 ignored artifacts。
METADATA_SHA = '2490286738f7b4095bf479eaa81c8764e68d27411993ac0d2c32c4daaceceeee'
NOW = datetime(2026, 10, 4, 12)
CDN_URL = 'https://img.scoregg.com/match/resultlist/20839.json'
METADATA_URL = 'https://ho.scoregg.com/services/api_url.php'


@pytest.fixture
def metadata():
    encoded = METADATA_FILE.read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == METADATA_SHA
    return json.loads(encoded)


def response(payload=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = (json.dumps(payload).encode() if payload is not None else b'<Error>Not Found</Error>')
    return result


class Transport:
    def __init__(self, *events):
        self.events = iter(events)
        self.headers = {}
        self.calls = []

    def _receive(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        event = next(self.events)
        if isinstance(event, Exception):
            raise event
        event.url = url
        return event

    def get(self, url, **kwargs):
        return self._receive('GET', url, kwargs)

    def post(self, url, **kwargs):
        return self._receive('POST', url, kwargs)


def source(*events, budget=10, retries=0):
    clock = [0.0]
    transport = Transport(*events)
    client = spider.ScoreGGClient(spider.RequestBudget(budget, 60, clock=lambda: clock[0]),
                                 session=transport, retries=retries, min_interval=1,
                                 sleep=lambda delay: clock.__setitem__(0, clock[0] + delay))
    return client, transport, clock


def series_fixture(db, tmp_path):
    row = {'matchID': '20839', 'start_time': '1665698400', 'match_date': '2022-10-14',
           'match_time': '06:00', 'status': '2', 'teamID_a': '102', 'teamID_b': '1',
           'team_a_win': '0', 'team_b_win': '1', 'team_short_name_a': 'FNC',
           'team_short_name_b': 'EDG', 'is_publist': 1, 'game_count': '1'}
    raw_dir = tmp_path / 'raw'
    raw = history._archive(raw_dir / 'history/stages/317/2432.json', [row])
    tour = HistoryTournament(tournament_id=317, name='S12世界总决赛', status='discovered')
    db.session.add(tour)
    db.session.flush()
    stage = HistoryStage(tournament_id=317, cache_key='2432', parent_round_id=754,
                         status='discovered', raw_file=raw[0], raw_sha256=raw[1], series_count=1)
    db.session.add(stage)
    db.session.flush()
    series = HistorySeries(series_id=20839, tournament_id=317, stage_id=stage.id,
                           scheduled_at=datetime(2022, 10, 14, 6), source_status='2', is_publist=1,
                           team_a_score=0, team_b_score=1, source_json=json.dumps(row),
                           schedule_raw_file=raw[0], schedule_raw_sha256=raw[1])
    db.session.add(series)
    db.session.commit()
    return series, raw_dir


def manifests(raw_dir):
    return [json.loads(path.read_bytes()) for path in raw_dir.glob('history/resultlist-fallback/20839/*/evidence-*.json')]


def test_real_metadata_ids_are_discovered_with_two_counted_sources_and_raw_evidence(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    client, transport, clock = source(response(status=404), response(metadata))
    outcome = history._discover_resultlist(client, series, raw_dir, NOW)
    assert series.status == 'discovered' and json.loads(series.result_ids) == [35121]
    assert db.session.query(Match).count() == 0
    task = db.session.query(SyncTask).one()
    assert (task.result_id, task.series_id, task.tournament_id, task.scheduled_at) == (
        35121, 20839, 317, datetime(2022, 10, 14, 6))
    assert client.budget.count == 2 and clock[0] == 1
    assert [(method, url) for method, url, _ in transport.calls] == [('GET', CDN_URL), ('POST', METADATA_URL)]
    request = transport.calls[1][2]
    assert request['allow_redirects'] is False
    assert request['data'] == {'api_path': '/services/match/match_info_new.php', 'method': 'post',
                               'platform': 'web', 'api_version': '9.9.9', 'language_id': '1', 'matchID': 20839}
    evidence = outcome['resultlist_evidence']
    assert evidence['cdn']['http_status'] == 404 and evidence['source'] == 'scoregg_match_metadata'
    assert Path(evidence['cdn']['response']['raw_file']).read_bytes() == b'<Error>Not Found</Error>'
    assert json.loads(Path(series.raw_file).read_bytes()) == metadata
    assert series.raw_sha256 == hashlib.sha256(Path(series.raw_file).read_bytes()).hexdigest()
    assert not (raw_dir / 'history/resultlists/20839.json').exists()


def test_full_detail_404_remains_failed_after_genuine_list_discovery(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    client, _, _ = source(response(status=404), response(metadata), response(status=404))
    report, code = pipeline.run_pipeline('history', client=client, raw_dir=raw_dir,
                                         reports_dir=tmp_path / 'reports', now=NOW)
    assert code == 2 and report['status'] == 'partial' and report['request_count'] == 3
    assert series.status == 'discovered' and db.session.query(SyncTask).one().status == 'failed'
    assert db.session.query(Match).count() == 0
    assert report['details']['coverage']['complete_available'] is False
    assert any(item.get('resultlist_evidence', {}).get('result_ids') == [35121]
               for item in report['details']['outcomes'])


def test_complete_archived_metadata_is_reused_without_http_or_overwriting(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    client, _, _ = source(response(status=404), response(metadata))
    history._discover_resultlist(client, series, raw_dir, NOW)
    frozen = {path: path.read_bytes() for path in raw_dir.rglob('*') if path.is_file()}
    series.status = 'queued'
    db.session.commit()
    cached, transport, _ = source()
    outcome = history._discover_resultlist(cached, series, raw_dir, NOW)
    assert outcome['resultlist_evidence']['reused_raw'] is True
    assert cached.budget.count == 0 and transport.calls == []
    assert {path: path.read_bytes() for path in raw_dir.rglob('*') if path.is_file()} == frozen


def test_changed_schedule_does_not_pin_discovery_to_stale_metadata_cache(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    client, _, _ = source(response(status=404), response(metadata))
    history._discover_resultlist(client, series, raw_dir, NOW)
    frozen = {path: path.read_bytes() for path in raw_dir.rglob('*') if path.is_file()}
    row = json.loads(series.source_json)
    row['start_time'], row['match_time'] = str(int(row['start_time']) + 3600), '07:00'
    stage = db.session.get(HistoryStage, series.stage_id)
    new_raw = history._archive_stage_payload(stage, raw_dir, [row])
    stage.raw_file, stage.raw_sha256 = new_raw
    series.schedule_raw_file, series.schedule_raw_sha256 = new_raw
    series.source_json, series.scheduled_at, series.status = json.dumps(row), datetime(2022, 10, 14, 7), 'queued'
    metadata['data']['start_time'] = row['start_time']
    db.session.commit()
    refreshed, transport, _ = source(response(status=404), response(metadata))
    outcome = history._discover_resultlist(refreshed, series, raw_dir, NOW)
    assert series.status == 'discovered' and refreshed.budget.count == 2
    assert len(transport.calls) == 2 and not outcome['resultlist_evidence'].get('reused_raw')
    assert db.session.query(SyncTask).one().scheduled_at == datetime(2022, 10, 14, 7)
    assert all(path.read_bytes() == encoded for path, encoded in frozen.items())


@pytest.mark.parametrize('case', ['wrong_bo', 'wrong_tournament', 'wrong_game', 'wrong_team', 'same_teams',
                                 'wrong_time', 'not_ended', 'multi_teams', 'wrong_score', 'bad_code',
                                 'wrong_count', 'bad_game_count', 'duplicate_id', 'zero_id', 'malformed_id',
                                 'wrong_result_teams', 'wrong_winner', 'same_winner_loser', 'wrong_result_bo',
                                 'unknown_detail_route', 'too_many_wins', 'not_list'])
def test_metadata_known_identity_and_list_conflicts_never_queue_or_import(db, tmp_path, metadata, case):
    series, raw_dir = series_fixture(db, tmp_path)
    data = metadata['data']
    row = data['result_list'][0]
    mutations = {
        'wrong_bo': (data, 'matchID', '20840'), 'wrong_tournament': (data, 'tournamentID', '318'),
        'wrong_game': (data, 'gameID', '2'), 'wrong_team': (data, 'teamID_a', '999'),
        'same_teams': (data, 'teamID_a', '1'), 'wrong_time': (data, 'start_time', '1665698401'),
        'not_ended': (data, 'status', '1'), 'multi_teams': (data, 'more_team_list', [102, 1, 2]),
        'wrong_score': (data, 'team_b_win', '2'), 'bad_code': (metadata, 'code', 500),
        'wrong_count': (data, 'result_count', '2'), 'bad_game_count': (data, 'game_count', '0'),
        'zero_id': (row, 'resultID', '0'), 'malformed_id': (row, 'resultID', '35121.0'),
        'wrong_result_teams': (row, 'teamID_a', '999'), 'wrong_winner': (row, 'win_teamID', '999'),
        'same_winner_loser': (row, 'los_teamID', 1), 'wrong_result_bo': (row, 'matchID', '20840'),
        'unknown_detail_route': (row, 'url', 'other'), 'too_many_wins': (row, 'win_teamID', '102'),
        'not_list': (data, 'result_list', {}),
    }
    if case == 'duplicate_id':
        data['result_list'].append(copy.deepcopy(row))
        data['result_count'] = data['game_count'] = '2'
        data['team_b_win'] = '2'
        schedule_row = json.loads(series.source_json)
        schedule_row.update(game_count='2', team_b_win='2')
        series.source_json = json.dumps(schedule_row)
        series.team_b_score = 2
        raw = history._archive(Path(series.schedule_raw_file), [schedule_row])
        series.schedule_raw_sha256 = raw[1]
        db.session.commit()
    else:
        obj, key, value = mutations[case]
        obj[key] = value
    client, _, _ = source(response(status=404), response(metadata))
    with pytest.raises(spider.SourceError):
        history._discover_resultlist(client, series, raw_dir, NOW)
    db.session.rollback()
    assert db.session.query(Match).count() == db.session.query(SyncTask).count() == 0
    assert series.result_ids == '[]'
    assert client.budget.count == 2
    assert any(item['status'] == 'failed' for item in manifests(raw_dir))


def test_empty_metadata_remains_pending_and_is_refreshed_instead_of_cached_forever(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    metadata['data']['result_list'] = []
    metadata['data']['result_count'] = '0'
    client, _, _ = source(response(status=404), response(metadata))
    outcome = history._discover_resultlist(client, series, raw_dir, NOW)
    assert series.status == 'pending' and outcome['resultlist_evidence']['list_complete'] is False
    assert db.session.query(SyncTask).count() == 0
    series.status = 'queued'
    db.session.commit()
    refreshed, _, _ = source(response(status=404), response(json.loads(METADATA_FILE.read_bytes())))
    history._discover_resultlist(refreshed, series, raw_dir, NOW)
    assert series.status == 'discovered' and refreshed.budget.count == 2


def test_partial_list_queues_reliable_ids_but_does_not_claim_complete_final_series(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    row = json.loads(series.source_json)
    row.update(team_a_win='1', team_b_win='2', game_count='3')
    series.source_json = json.dumps(row)
    series.team_a_score, series.team_b_score = 1, 2
    raw = history._archive(Path(series.schedule_raw_file), [row])
    series.schedule_raw_sha256 = raw[1]
    metadata['data'].update(team_a_win='1', team_b_win='2', game_count='3')
    db.session.commit()
    client, _, _ = source(response(status=404), response(metadata))
    outcome = history._discover_resultlist(client, series, raw_dir, NOW)
    assert json.loads(series.result_ids) == [35121] and db.session.query(SyncTask).one().status == 'queued'
    assert series.status == 'pending' and series.next_retry_at is not None
    assert outcome['resultlist_evidence']['list_complete'] is False
    assert history.coverage_report()['complete_available'] is False


def test_finished_bo5_with_three_actual_results_is_complete_without_inventing_two_games(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    row = json.loads(series.source_json)
    row.update(team_a_win='0', team_b_win='3', game_count='5')
    series.source_json = json.dumps(row)
    series.team_b_score = 3
    raw = history._archive(Path(series.schedule_raw_file), [row])
    series.schedule_raw_sha256 = raw[1]
    metadata['data'].update(team_b_win='3', game_count='5', result_count='3')
    # 合成不同单局 ID 仅用于隔离 BO 格式用例，不请求或声称真实来源存在。
    for identifier in (99001, 99002):
        item = copy.deepcopy(metadata['data']['result_list'][0])
        item['resultID'] = str(identifier)
        metadata['data']['result_list'].append(item)
    db.session.commit()
    client, _, _ = source(response(status=404), response(metadata))
    outcome = history._discover_resultlist(client, series, raw_dir, NOW)
    assert series.status == 'discovered' and outcome['resultlist_evidence']['list_complete'] is True
    assert json.loads(series.result_ids) == [35121, 99001, 99002]
    assert db.session.query(SyncTask).count() == 3


def test_known_bo_format_conflict_is_failed_without_queueing_even_when_counts_match(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    metadata['data']['game_count'] = '5'
    client, _, _ = source(response(status=404), response(metadata))
    with pytest.raises(spider.SourceError, match='BO 格式'):
        history._discover_resultlist(client, series, raw_dir, NOW)
    assert db.session.query(SyncTask).count() == 0


@pytest.mark.parametrize('games,score_a,score_b', [(3, 2, 2), (0, 0, 1)])
def test_impossible_final_score_exceeding_maximum_games_stays_failed_with_original_backoff(
        db, tmp_path, metadata, games, score_a, score_b):
    series, raw_dir = series_fixture(db, tmp_path)
    row = json.loads(series.source_json)
    row.update(game_count=str(games), team_a_win=str(score_a), team_b_win=str(score_b))
    series.source_json = json.dumps(row)
    series.team_a_score, series.team_b_score = score_a, score_b
    series.status, series.failure_count = 'failed', 4
    raw = history._archive(Path(series.schedule_raw_file), [row])
    series.schedule_raw_sha256 = raw[1]
    metadata['data'].update(game_count=str(games), team_a_win=str(score_a), team_b_win=str(score_b))
    if games == 0:
        metadata['data'].update(result_list=[], result_count='0')
    db.session.commit()
    with pytest.raises(spider.SourceError, match='最终比分超过 BO 最大局数'):
        spider.metadata_result_list(metadata, series.schedule())
    client, _, _ = source(response(status=404), response(metadata))
    report, code = pipeline.run_pipeline('history', client=client, raw_dir=raw_dir,
                                         reports_dir=tmp_path / 'reports', now=NOW)
    assert code == 2 and report['status'] == 'partial'
    assert series.status == 'failed' and series.failure_count == 5 and series.next_retry_at is not None
    assert db.session.query(SyncTask).count() == db.session.query(Match).count() == 0
    assert report['details']['coverage']['exhausted_tasks'] == 1


def test_real_bo27625_declared_two_results_with_empty_list_is_failed_not_pending_or_complete(db, tmp_path):
    fixture = Path(__file__).parent / 'fixtures' / 'scoregg_bo27625_metadata.json'
    encoded = fixture.read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == '0925b6b18c2a49ac148bca89e40ffcdc0f39e0d71c5f78b2ec18270174bd8f6e'
    metadata = json.loads(encoded)
    series, raw_dir = series_fixture(db, tmp_path)
    # 本地赛程夹具按此真实响应身份对齐，确保失败针对 count2/list0，而非另一 BO。
    data = metadata['data']
    row = json.loads(series.source_json)
    row.update(matchID=data['matchID'], start_time=data['start_time'],
               match_date='2022-12-11', match_time='16:00', teamID_a=data['teamID_a'],
               teamID_b=data['teamID_b'], team_a_win=data['team_a_win'], team_b_win=data['team_b_win'],
               game_count=data['game_count'])
    db.session.add(HistoryTournament(tournament_id=430, name='测试夹具', status='discovered'))
    db.session.flush()
    series.series_id, series.tournament_id = 27625, 430
    series.scheduled_at = datetime(2022, 12, 11, 16)
    series.team_a_score = series.team_b_score = 1
    series.source_json = json.dumps(row)
    series.status, series.failure_count = 'failed', 4
    raw = history._archive(raw_dir / 'history/stages/430/fixture.json', [row])
    series.schedule_raw_file, series.schedule_raw_sha256 = raw
    stage = db.session.get(HistoryStage, series.stage_id)
    stage.tournament_id, stage.raw_file, stage.raw_sha256 = 430, raw[0], raw[1]
    db.session.commit()
    client, transport, _ = source(response(status=404), response(metadata))
    report, code = pipeline.run_pipeline('history', client=client, raw_dir=raw_dir,
                                         reports_dir=tmp_path / 'reports', now=NOW)
    assert code == 2 and report['status'] == 'partial'
    assert series.status == 'failed' and series.failure_count == 5 and series.next_retry_at is not None
    assert 'result_count/game_count' in series.last_error
    assert report['details']['coverage']['exhausted_tasks'] == 1
    assert len(transport.calls) == 2 and client.budget.count == 2
    assert series.result_ids == '[]' and db.session.query(SyncTask).count() == 0
    evidence = [json.loads(p.read_bytes()) for p in raw_dir.glob('history/resultlist-fallback/27625/*/evidence-*.json')]
    failed = next(item for item in evidence if item['status'] == 'failed')
    assert failed['cdn']['http_status'] == 404
    assert json.loads(Path(failed['metadata']['responses'][0]['response']['raw_file']).read_bytes()) == metadata


def test_budget_after_cdn404_preserves_evidence_and_does_not_start_metadata_or_tasks(db, tmp_path):
    series, raw_dir = series_fixture(db, tmp_path)
    client, transport, _ = source(response(status=404), budget=1)
    with pytest.raises(spider.BudgetExceeded):
        history._discover_resultlist(client, series, raw_dir, NOW)
    assert client.budget.count == 1 and len(transport.calls) == 1
    assert db.session.query(SyncTask).count() == 0
    assert any(item['status'] == 'budget_exhausted' and item['cdn']['http_status'] == 404 for item in manifests(raw_dir))


@pytest.mark.parametrize('status', [403, 429, 500])
def test_only_cdn404_can_trigger_fallback(db, tmp_path, status):
    series, raw_dir = series_fixture(db, tmp_path)
    client, transport, _ = source(response(status=status))
    with pytest.raises(spider.SourceHTTPError):
        history._discover_resultlist(client, series, raw_dir, NOW)
    assert len(transport.calls) == 1 and not manifests(raw_dir)


@pytest.mark.parametrize('case', ['missing_row', 'missing_archive', 'bad_sha', 'duplicate_row', 'missing_team',
                                 'future', 'live', 'unpublished', 'date_conflict'])
def test_missing_or_conflicting_schedule_never_spends_a_metadata_request(db, tmp_path, case):
    series, raw_dir = series_fixture(db, tmp_path)
    row = json.loads(series.source_json)
    if case == 'missing_row':
        series.source_json = None
    elif case == 'missing_archive':
        series.schedule_raw_file = series.schedule_raw_sha256 = None
        stage = db.session.get(HistoryStage, series.stage_id)
        stage.raw_file = stage.raw_sha256 = None
    elif case == 'bad_sha':
        series.schedule_raw_sha256 = '0' * 64
    elif case == 'duplicate_row':
        raw = history._archive(Path(series.schedule_raw_file), [row, row])
        series.schedule_raw_sha256 = raw[1]
    elif case == 'missing_team':
        del row['teamID_a']
        series.source_json = json.dumps(row)
    elif case == 'future':
        series.scheduled_at = datetime(2030, 1, 1)
    elif case == 'live':
        series.source_status = '1'
    elif case == 'unpublished':
        series.is_publist = 0
    else:
        series.scheduled_at = datetime(2022, 10, 14, 7)
    db.session.commit()
    client, transport, _ = source(response(status=404))
    if case in ('future', 'live', 'unpublished'):
        history._discover_resultlist(client, series, raw_dir, NOW)
        assert series.status == 'pending'
    else:
        with pytest.raises((spider.SourceError, ValueError)):
            history._discover_resultlist(client, series, raw_dir, NOW)
    assert all(method == 'GET' for method, _, _ in transport.calls)
    assert db.session.query(SyncTask).count() == 0


def test_metadata_retries_are_bounded_rate_limited_and_all_responses_archived(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    client, transport, clock = source(response(status=404), response(status=500), response(metadata), retries=1)
    history._discover_resultlist(client, series, raw_dir, NOW)
    assert client.budget.count == 3 and clock[0] >= 2
    assert [method for method, _, _ in transport.calls] == ['GET', 'POST', 'POST']
    evidence = next(item for item in manifests(raw_dir) if item['status'] == 'validated')
    assert [item['http_status'] for item in evidence['metadata']['responses']] == [500, 200]


@pytest.mark.parametrize('event', [response(status=404), response(status=302), response({'code': 500}),
                                 requests.Timeout('metadata timeout')])
def test_metadata_failure_keeps_original404_and_never_claims_empty_success(db, tmp_path, event):
    series, raw_dir = series_fixture(db, tmp_path)
    client, _, _ = source(response(status=404), event)
    with pytest.raises(spider.SourceError, match='CDN HTTP404'):
        history._discover_resultlist(client, series, raw_dir, NOW)
    assert client.budget.count == 2 and db.session.query(SyncTask).count() == 0
    assert any(item['status'] == 'failed' for item in manifests(raw_dir))


def test_daily_uses_same_fallback_and_keeps_detail_failed(db, tmp_path, metadata):
    series, raw_dir = series_fixture(db, tmp_path)
    from app.models.sync import SyncRun
    run = SyncRun(command='daily')
    db.session.add(run)
    db.session.commit()
    client, _, _ = source(response(status=404), response(metadata), response(status=404))
    outcomes = []
    pipeline._fetch_series(client, series.schedule(), run, raw_dir, outcomes, 5, NOW)
    assert client.budget.count == 3 and db.session.query(Match).count() == 0
    assert any(item.get('resultlist_evidence', {}).get('result_ids') == [35121] for item in outcomes)
    assert any(item.get('result_id') == 35121 and item['status'] == 'failed' for item in outcomes)
    assert db.session.query(SyncTask).filter_by(result_id=35121).one().status == 'failed'
