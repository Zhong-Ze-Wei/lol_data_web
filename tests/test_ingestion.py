import copy
import json
from datetime import datetime
from pathlib import Path

import pytest
import requests
from sqlalchemy.exc import IntegrityError

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import SyncTask
from app.services import ingestion
from app.services.ingestion import ingest_result, normalize_result, NonLOLResult
from app.services.spider import BudgetExceeded, RequestBudget, ScoreGGClient, SourceError, SourceHTTPError, discover_series
from scripts.pipeline import AlreadyRunning, PipelineLock, run_pipeline


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / 'fixtures' / 'scoregg_result_66845.json').read_text(encoding='utf-8'))


def test_result_id_and_series_id_are_distinct_and_schedule_wins(payload):
    schedule = {'series_id': 58146, 'tournament_id': 1007, 'tournament_name': 'LPL',
                'scheduled_at': datetime(2026, 7, 22, 17)}
    data = normalize_result(payload, 66845, schedule)
    match = data['matches'][0]
    assert match['match_id'] == 66845
    assert match['series_id'] == 58146
    assert match['date'] == schedule['scheduled_at']
    assert match['date_source'] == 'schedule'
    assert match['game_time'] == 41 * 60 + 49
    assert len(data['teams']) == 2 and len(data['players']) == 10
    assert data['players'][0]['part'] == 38.1


def test_game_id_accepts_chinese_lol_and_rejects_english_non_lol(payload):
    payload['data']['result_list']['red_name'] = '中文战队'
    assert normalize_result(payload, 66845)['matches'][0]['red_team_name'] == '中文战队'
    payload['data']['gameID'] = '2'
    payload['data']['result_list']['red_name'] = 'EnglishTeam'
    with pytest.raises(NonLOLResult):
        normalize_result(payload, 66845)


def test_upsert_does_not_grow_and_preserves_known_schedule_and_optional_fields(db, payload):
    schedule = {'series_id': 58146, 'scheduled_at': datetime(2026, 7, 22, 17)}
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    photo = db.session.query(Player).filter_by(position='a', team_name='LGD').one().pic
    payload['data']['result_list']['red_star_a_kills'] = '9'
    payload['data']['result_list'].pop('red_star_a_pic')
    assert ingest_result(payload, 66845).status == 'imported'
    assert db.session.query(Match).count() == 1
    assert db.session.query(Team).count() == 2
    assert db.session.query(Player).count() == 10
    player = db.session.query(Player).filter_by(position='a', team_name='LGD').one()
    assert player.kills == 9 and player.pic == photo
    assert db.session.query(Match).one().date == schedule['scheduled_at']
    assert db.session.query(SyncTask).one().status == 'imported'


def test_transaction_rolls_back_whole_match_and_retains_failed_task(db, payload, monkeypatch):
    original = ingestion.bulk_upsert

    def fail_teams(model, rows, keys, session=None, preserve_nulls=True):
        if model is Team:
            raise IntegrityError('simulated_team_insert', {}, Exception('simulated failure'))
        return original(model, rows, keys, session, preserve_nulls=preserve_nulls)

    monkeypatch.setattr(ingestion, 'bulk_upsert', fail_teams)
    outcome = ingest_result(payload, 66845)
    assert outcome.status == 'failed'
    assert db.session.query(Match).count() == 0
    assert db.session.query(Team).count() == 0
    assert db.session.query(Player).count() == 0
    assert db.session.query(SyncTask).one().status == 'failed'


def test_incomplete_result_is_not_imported_as_complete(db, payload):
    del payload['data']['result_list']['blue_star_e_name']
    assert ingest_result(payload, 66845).status == 'failed'
    assert db.session.query(Match).count() == 0
    assert db.session.query(SyncTask).one().last_error


def test_source_failure_is_failed_instead_of_unfinished(db):
    outcome = ingest_result({'code': 500, 'message': 'upstream broken', 'data': []}, 66845)
    assert outcome.status == 'failed'
    assert db.session.query(SyncTask).one().status == 'failed'


class FakeSession:
    def __init__(self, events):
        self.events = iter(events)
        self.headers = {}
        self.timeouts = []

    def get(self, url, timeout):
        self.timeouts.append(timeout)
        event = next(self.events)
        if isinstance(event, Exception):
            raise event
        return event


def response(status=200, body='{}', retry_after=None):
    item = requests.Response()
    item.status_code = status
    item._content = body.encode()
    if retry_after is not None:
        item.headers['Retry-After'] = retry_after
    return item


def test_timeout_retry_is_bounded_and_explicit():
    session = FakeSession([requests.Timeout('timeout')] * 3)
    waits = []
    client = ScoreGGClient(RequestBudget(10, 30), session, retries=2, sleep=waits.append)
    with pytest.raises(SourceError, match='Timeout'):
        client.get_result(66845)
    assert client.budget.count == 3
    assert waits == [1, 2]
    assert all(connect <= 5 and read <= 20 for connect, read in session.timeouts)


def test_retry_after_and_request_budget():
    waits = []
    session = FakeSession([response(429, retry_after='2'), response()])
    client = ScoreGGClient(RequestBudget(2, 30), session, sleep=waits.append)
    assert client.get_json('https://example.test/public') == {}
    assert waits == [2]
    with pytest.raises(BudgetExceeded):
        client.get_json('https://example.test/public')


def test_time_budget_prevents_requests_after_deadline():
    clock = [0.0]
    budget = RequestBudget(10, 5, clock=lambda: clock[0])
    budget.reserve()
    clock[0] = 5.0
    with pytest.raises(BudgetExceeded, match='时间预算'):
        budget.reserve()
    assert budget.count == 1


def test_failed_source_is_persisted_and_manual_retry_recovers(db, payload, tmp_path):
    class BrokenClient:
        budget = RequestBudget(10, 30)

        def get_result(self, result_id):
            self.budget.reserve()
            raise SourceError('Timeout after finite retries')

    report, code = run_pipeline('backfill', client=BrokenClient(), start=66845, end=66845,
                                raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')
    assert code == 2 and report['failed'] == 1
    task = db.session.query(SyncTask).one()
    assert task.status == 'failed' and task.next_retry_at is not None and task.failure_count == 1

    class HealthyClient:
        budget = RequestBudget(10, 30)

        def get_result(self, result_id):
            self.budget.reserve()
            return payload

    report, code = run_pipeline('retry', client=HealthyClient(), force=True,
                                raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')
    assert code == 0 and report['imported'] == 1
    assert db.session.query(SyncTask).one().failure_count == 0
    assert db.session.query(Match).one().verified is True


def test_no_stop_after_105_empty_result_ids(db, payload, tmp_path):
    class Client:
        budget = RequestBudget(130, 30)

        def get_result(self, result_id):
            self.budget.reserve()
            return copy.deepcopy(payload) if result_id == 106 else {'code': 200, 'data': []}

    report, code = run_pipeline('backfill', client=Client(), start=1, end=106,
                                raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')
    assert code == 0 and report['imported'] == 1
    assert db.session.query(Match).one().match_id == 106
    assert db.session.query(SyncTask).count() == 106
    assert report['request_count'] == 106
    assert (tmp_path / 'raw' / 'scoregg' / '106.json').exists()


def test_stage_without_children_uses_parent_cache_and_series_mapping():
    class Client:
        seen = []

        def get(self, url):
            return type('Page', (), {'text': 'var t_data = {"gameID":"1","tournament_list":[{"tournamentID":"1007","start_date":"2026-07-01","end_date":"2026-07-31","name":"LPL"}]}; window.x=1;'})()

        def get_json(self, url):
            self.seen.append(url)
            if '/tr/' in url:
                return [{'roundID': '2255', 'round_son': []}]
            assert url.endswith('/tr_round/p_2255.json')
            return [{'matchID': '58146', 'match_date': '2026-07-22', 'match_time': '17:00', 'status': '2'}]

    client = Client()
    schedules, info = discover_series(client, datetime(2026, 7, 23))
    assert schedules[0]['series_id'] == 58146
    assert schedules[0]['tournament_id'] == 1007
    assert info['source_stale'] is False


def test_real_archived_tournament_unknown_dates_do_not_block_active_discovery():
    class Client:
        def get(self, url):
            page = {'gameID': '1', 'tournament_list': [
                {'tournamentID': '1007', 'name': '2026 LPL', 'start_date': '2026-07-01', 'end_date': '2026-07-31'},
                {'tournamentID': '399', 'name': '2016 CBLOL 冬季赛', 'start_date': '0000-00-00', 'end_date': '0000-00-00'},
            ]}
            return type('Page', (), {'text': 'var t_data = ' + json.dumps(page) + ';'})()

        def get_json(self, url):
            if '/tr/' in url:
                return [{'roundID': '2255', 'round_son': []}]
            return [{'matchID': '58146', 'match_date': '2026-07-22', 'match_time': '17:00', 'status': '2'}]

    schedules, report = discover_series(Client(), datetime(2026, 7, 23))
    assert len(schedules) == 1
    assert report['discovery_errors'] == []
    assert report['excluded_tournaments'][0]['tournament_id'] == '399'


def test_daily_waiting_series_does_not_request_results_and_completed_404_is_failed(db, tmp_path):
    class Client:
        budget = RequestBudget(30, 30)
        requested_results = []

        def get(self, url):
            self.budget.reserve()
            page = {'gameID': '1', 'tournament_list': [
                {'tournamentID': '1007', 'name': 'LPL', 'start_date': '2026-07-01', 'end_date': '2026-07-31'},
            ]}
            return type('Page', (), {'text': 'var t_data = ' + json.dumps(page) + ';'})()

        def get_json(self, url):
            self.budget.reserve()
            if '/tr/' in url:
                return [{'roundID': '2255', 'round_son': []}]
            return [
                {'matchID': '58146', 'match_date': '2026-07-22', 'match_time': '17:00', 'status': '2', 'is_publist': 1},
                {'matchID': '59379', 'match_date': '2026-07-23', 'match_time': '07:00', 'status': '0'},
                {'matchID': '59380', 'match_date': '2026-07-23', 'match_time': '21:00', 'status': '2'},
                {'matchID': '59381', 'match_date': '2026-07-24', 'match_time': '21:00', 'status': '0'},
            ]

        def get_result_ids(self, series_id):
            self.budget.reserve()
            self.requested_results.append(series_id)
            raise SourceHTTPError('https://example.test/completed-series', 404)

    client = Client()
    report, code = run_pipeline('daily', client=client, now=datetime(2026, 7, 23, 8),
                                raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')
    assert client.requested_results == [58146]
    assert code == 2 and report['failed'] == 1
    assert db.session.query(SyncTask).filter_by(series_id=58146).one().status == 'failed'
    assert db.session.query(SyncTask).filter_by(series_id=59379).one().status == 'pending'
    assert db.session.query(SyncTask).filter_by(series_id=59380).one().status == 'pending'
    assert report['details']['latest_schedule_date'] == '2026-07-22T17:00:00'
    assert report['details']['latest_published_schedule_date'] == '2026-07-24T21:00:00'


def test_finished_score_only_series_waits_for_public_report_and_retry_leaves_it_to_daily(db, tmp_path):
    class Client:
        budget = RequestBudget(30, 30)

        def get(self, url):
            self.budget.reserve()
            page = {'gameID': '1', 'tournament_list': [
                {'tournamentID': '1028', 'name': 'WSCI', 'start_date': '2026-07-01', 'end_date': '2026-07-31'},
            ]}
            return type('Page', (), {'text': 'var t_data = ' + json.dumps(page) + ';'})()

        def get_json(self, url):
            self.budget.reserve()
            if '/tr/' in url:
                return [{'roundID': '2268', 'round_son': []}]
            return [{'matchID': '59222', 'match_date': '2026-07-22', 'match_time': '17:00',
                     'status': '2', 'is_publist': 0, 'team_a_win': '2', 'team_b_win': '3'}]

        def get_result_ids(self, series_id):
            raise AssertionError('官网明确战报未发布，不应请求不存在的结果列表')

    client = Client()
    report, code = run_pipeline('daily', client=client, now=datetime(2026, 7, 23, 8),
                                raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')
    assert code == 0 and report['failed'] == 0 and report['skipped'] == 1
    task = db.session.query(SyncTask).one()
    assert task.status == 'pending' and task.failure_count == 0
    outcome = report['details']['outcomes'][0]
    assert outcome['source_status'] == '2' and outcome['is_publist'] == 0
    assert outcome['series_score'] == ['2', '3']
    assert db.session.query(Match).count() == 0
    requests_before = client.budget.count
    retry_report, code = run_pipeline('retry', client=client, force=True,
                                      raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')
    assert code == 0 and retry_report['details']['selected_tasks'] == 0
    assert client.budget.count == requests_before
    assert db.session.query(SyncTask).one().status == 'pending'


def test_unpublished_parent_stage_404_is_audited_and_published_404_is_error():
    class Client:
        published = [{'id': '2224'}]

        def get(self, url):
            page = {'gameID': '1', 'tournament_list': [
                {'tournamentID': '1008', 'name': 'LCP', 'start_date': '2026-07-25', 'end_date': '2026-09-20'},
            ], 'week_player_select_list': self.published}
            return type('Page', (), {'text': 'var t_data = ' + json.dumps(page) + ';'})()

        def get_json(self, url):
            if '/tr/' in url:
                return [{'roundID': '2224', 'round_son': [], 'is_now_week': 0},
                        {'roundID': '2225', 'name': '季后赛', 'round_son': [], 'is_now_week': 0}]
            if url.endswith('p_2225.json'):
                raise SourceHTTPError(url, 404)
            return [{'matchID': '58636', 'match_date': '2026-09-19', 'match_time': '17:00', 'status': '2'}]

    client = Client()
    schedules, report = discover_series(client, datetime(2026, 9, 20))
    assert len(schedules) == 1
    assert report['discovery_errors'] == []
    assert report['unpublished_stages'][0]['round_id'] == '2225'
    client.published = [{'id': '2224'}, {'id': '2225'}]
    _, report = discover_series(client, datetime(2026, 9, 20))
    assert report['discovery_errors'][0]['tournament_id'] == 1008
    assert report['unpublished_stages'] == []


def test_process_lock_blocks_overlapping_runs(tmp_path):
    with PipelineLock(tmp_path / '.sync.lock'):
        with pytest.raises(AlreadyRunning):
            with PipelineLock(tmp_path / '.sync.lock'):
                pass
    with PipelineLock(tmp_path / '.sync.lock'):
        pass


def test_non_lol_confirmation_only_removes_unverified_legacy(db, payload):
    db.session.add(Match(match_id=66845, source='legacy', verified=False))
    db.session.add(Team(match_id=66845, team_name='EnglishTeam'))
    db.session.add(Player(match_id=66845, team_name='EnglishTeam', position='a', name='Player'))
    db.session.commit()
    payload['data']['gameID'] = '2'
    assert ingest_result(payload, 66845).status == 'skipped'
    assert db.session.query(Match).count() == db.session.query(Team).count() == db.session.query(Player).count() == 0
    assert db.session.query(SyncTask).one().status == 'skipped'
