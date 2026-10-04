import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import HistoryTournament, HistoryStage, HistorySeries, SyncTask, utc_now
from app.services.history import coverage_report, repair_archived_results, repair_verified_raw
from app.services import history, ingestion
from app.services.ingestion import ingest_result, normalize_result
from app.services.source_identity import build_source_name_index
from app.services.spider import RequestBudget, ScoreGGClient, SourceHTTPError
from scripts.pipeline import run_pipeline


@pytest.fixture
def result():
    payload = json.loads((Path(__file__).parent / 'fixtures' / 'scoregg_result_66845.json').read_text(encoding='utf-8'))
    payload['data']['max_mvp']['match_id'] = '20674'
    payload['data']['max_beiguo']['match_id'] = '20674'
    return payload


@pytest.fixture
def identity_result(result):
    """最小 fixture 原本省略身份字段；按真实战报的 ID+color 结构补齐。"""
    result['data']['teams'] = []
    for index, (side, position) in enumerate((side, pos) for side in ('red', 'blue') for pos in 'abcde'):
        identifier = '17863' if (side, position) == ('blue', 'e') else str(1000 + index)
        result['data']['result_list'][f'{side}_star_{position}_playerID'] = identifier
        result['data']['teams'].append({'playerID': identifier, 'color': side,
                                       'nickname': result['data']['result_list'][f'{side}_star_{position}_name']})
    return result


@pytest.fixture
def legacy_partial_result():
    # 原件最小投影，SHA256: 5d381a6c6ab18433ff38a28d796a0546853f974c6d49e2cefea775af610755a2。
    return json.loads((Path(__file__).parent / 'fixtures' / 'scoregg_result_18894_partial.json').read_text(encoding='utf-8'))


class HistoricalSource:
    def __init__(self, result, budget=50, pub=1, resultlist_error=False, stage_error=False):
        self.budget = RequestBudget(budget, 60)
        self.result = result
        self.calls = []
        self.pub = pub
        self.resultlist_error = resultlist_error
        self.stage_error = stage_error

    def _call(self, url):
        self.budget.reserve()
        self.calls.append(url)

    def get(self, url):
        self._call(url)
        page = {'gameID': '1', 'tournament_list': [
            {'tournamentID': '333', 'name': 'S1世界总决赛', 'start_date': '2011-06-18', 'end_date': '2011-06-21'}],
            'week_player_select_list': []}
        return SimpleNamespace(text='var t_data = ' + json.dumps(page) + ';')

    def get_json(self, url):
        self._call(url)
        if '/tr/' in url:
            return [{'roundID': '765', 'name': '分组', 'round_son': [], 'is_now_week': 0}]
        if self.stage_error:
            raise SourceHTTPError(url, 404)
        assert url.endswith('/tr_round/p_765.json')
        return [{'matchID': '20674', 'match_date': '2011-06-18', 'match_time': '16:30',
                 'status': '2', 'is_publist': self.pub, 'team_a_win': '1', 'team_b_win': '0'}]

    def get_result_list(self, series_id):
        self._call(f'resultlist/{series_id}')
        if self.resultlist_error:
            raise SourceHTTPError('https://img.scoregg.com/match/resultlist/20674.json', 404)
        return {'code': 200, 'data': [{'resultID': '66845'}]}

    def get_result(self, result_id):
        self._call(f'result/{result_id}')
        return copy.deepcopy(self.result)


def run(source, tmp_path, **kwargs):
    return run_pipeline('history', client=source, raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports',
                        now=datetime(2026, 10, 3), **kwargs)


def test_history_resumes_budget_without_repeating_successful_prefix(db, result, tmp_path):
    first = HistoricalSource(result, budget=2)
    report, code = run(first, tmp_path)
    assert code == 4 and report['status'] == 'budget_exhausted'
    assert db.session.query(HistoryTournament).one().status == 'discovered'
    assert db.session.query(HistoryStage).one().status == 'queued'
    assert report['details']['coverage']['has_runnable_work'] is True
    second = HistoricalSource(result, budget=2)
    report, code = run(second, tmp_path)
    assert code == 4 and second.calls == ['https://img.scoregg.com/tr_round/p_765.json', 'resultlist/20674']
    third = HistoricalSource(result, budget=1)
    report, code = run(third, tmp_path)
    assert code == 0 and third.calls == ['result/66845']
    assert db.session.query(Match).count() == 1
    assert db.session.query(Player).count() == 10 and db.session.query(Team).count() == 2
    match = db.session.query(Match).one()
    assert match.date == datetime(2011, 6, 18, 16, 30) and match.date_source == 'schedule'
    coverage = report['details']['coverage']
    assert coverage['snapshot_completed'] is True
    assert coverage['years'][0]['year'] == '2011' and coverage['years'][0]['complete_results'] == 1
    assert json.loads((tmp_path / 'reports' / 'history-progress.json').read_text(encoding='utf-8'))['run_id'] == report['run_id']
    assert (tmp_path / 'raw' / 'history' / 'resultlists' / '20674.json').is_file()
    fourth = HistoricalSource(result)
    assert run(fourth, tmp_path)[1] == 0 and fourth.calls == []


def test_completed_but_unpublished_series_is_audited_without_guessing_ids(db, result, tmp_path):
    source = HistoricalSource(result, pub=0)
    report, code = run(source, tmp_path)
    assert code == 0 and not any('resultlist/' in url for url in source.calls)
    series = db.session.query(HistorySeries).one()
    assert series.status == 'pending' and series.source_status == '2' and series.is_publist == 0
    coverage = report['details']['coverage']
    assert coverage['discovery_complete'] is True and coverage['snapshot_completed'] is True
    assert coverage['complete_available'] is False and coverage['pending_publication'] == 1
    assert coverage['has_runnable_work'] is False and coverage['next_retry_at']
    series.next_retry_at = utc_now() - timedelta(seconds=1)
    db.session.commit()
    published = HistoricalSource(result, pub=1)
    report, code = run(published, tmp_path)
    assert code == 0 and len(published.calls) == 3
    assert published.calls[0].endswith('/tr_round/p_765.json')
    assert db.session.query(Match).one().verified is True


def test_completed_published_404_remains_failed_with_explicit_retry_deadline(db, result, tmp_path):
    source = HistoricalSource(result, resultlist_error=True)
    report, code = run(source, tmp_path)
    assert code == 2 and report['status'] == 'partial'
    assert db.session.query(HistorySeries).one().status == 'failed'
    coverage = report['details']['coverage']
    assert coverage['snapshot_completed'] is False and coverage['failed_tasks'] == 1
    assert coverage['next_retry_at'] and coverage['has_runnable_work'] is False
    waiting = HistoricalSource(result)
    report, code = run(waiting, tmp_path)
    assert code == 2 and report['status'] == 'waiting_retry' and waiting.calls == []


def test_unpublished_stage_keeps_404_and_page_evidence(db, result, tmp_path):
    source = HistoricalSource(result, stage_error=True)
    report, code = run(source, tmp_path)
    assert code == 0 and db.session.query(HistoryStage).one().status == 'pending'
    assert db.session.query(HistorySeries).count() == 0
    assert report['details']['coverage']['pending_publication'] == 1
    assert (tmp_path / 'raw' / 'history' / 'tournament_pages' / '333.json').is_file()


def test_source_missing_historical_duration_keeps_null_and_reports_partial(db, result, tmp_path):
    result['data']['result_list']['game_time_m'] = '0'
    result['data']['result_list']['game_time_s'] = '0'
    source = HistoricalSource(result)
    report, code = run(source, tmp_path)
    assert code == 0
    assert db.session.query(Match).one().game_time is None
    assert db.session.query(Player).count() == 10
    assert all(row.game_time is None for row in db.session.query(Player))
    assert db.session.query(SyncTask).one().status == 'source_incomplete'
    coverage = report['details']['coverage']
    assert coverage['counts']['results']['source_incomplete'] == 1
    assert coverage['counts']['results'].get('complete', 0) == 0
    assert coverage['snapshot_completed'] is True and coverage['complete_available'] is False
    rerun = HistoricalSource(result)
    assert run(rerun, tmp_path)[1] == 0 and rerun.calls == []


def test_source_missing_player_keeps_match_teams_and_known_roster_without_fabricating_identity(db, result, tmp_path):
    del result['data']['result_list']['blue_star_e_name']
    report, code = run(HistoricalSource(result), tmp_path)
    assert code == 0 and db.session.query(Match).count() == 1
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 9
    assert db.session.query(Team).filter_by(team_name='EDG').one().player_e_id is None
    assert db.session.query(SyncTask).one().status == 'source_incomplete'
    assert (tmp_path / 'raw' / 'scoregg' / '66845.json').is_file()
    assert report['details']['coverage']['years'][0]['source_incomplete'] == 1


def test_cached_verified_raw_enriches_real_date_without_detail_request(db, result, tmp_path):
    assert ingest_result(result, 66845).status == 'imported'
    match = db.session.query(Match).one()
    assert match.id != 66845 and match.date_source == 'updated_at'
    raw = tmp_path / 'raw' / 'scoregg' / '66845.json'
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(result), encoding='utf-8')
    source = HistoricalSource(result)
    report, code = run(source, tmp_path)
    assert code == 0 and len(source.calls) == 4
    assert 'result/66845' not in source.calls
    assert report['details']['outcomes'][0]['reused_raw'] is True
    assert db.session.query(Match).one().date_source == 'schedule'
    assert db.session.query(Match).one().date.year == 2011
    assert db.session.query(Match).count() == 1


def test_unknown_tournament_dates_are_not_excluded_and_true_year_comes_from_series(db, result, tmp_path):
    class Undated(HistoricalSource):
        def get(self, url):
            page = super().get(url)
            page.text = page.text.replace('2011-06-18', '0000-00-00').replace('2011-06-21', '0000-00-00')
            return page
    report, code = run(Undated(result), tmp_path)
    assert code == 0 and db.session.query(HistoryTournament).one().start_date is None
    years = {row['year']: row for row in report['details']['coverage']['years']}
    assert years['unknown']['tournaments'] == 1 and years['2011']['complete_results'] == 1


def test_global_interval_includes_all_urls_and_retry_attempts():
    class Clock:
        value = 0
        def now(self):
            return self.value
        def sleep(self, seconds):
            self.value += seconds
    class Session:
        headers = {}
        def __init__(self, clock):
            self.clock, self.times = clock, []
        def get(self, url, timeout):
            self.times.append(self.clock.value)
            return SimpleNamespace(status_code=200, raise_for_status=lambda: None)
    clock = Clock()
    session = Session(clock)
    client = ScoreGGClient(RequestBudget(4, 10, clock=clock.now), session=session,
                           sleep=clock.sleep, min_interval=1)
    for url in ('catalog', 'stage', 'resultlist', 'result'):
        client.get(url)
    assert session.times == [0, 1, 2, 3]


def test_all_first_small_batch_imports_newest_tournament_and_next_batch_continues(db, result, tmp_path):
    class TwoTournaments(HistoricalSource):
        def get(self, url):
            self._call(url)
            page = {'gameID': '1', 'tournament_list': [
                {'tournamentID': '149', 'name': 'S2', 'start_date': '2012-10-04', 'end_date': '2012-10-14'},
                {'tournamentID': '333', 'name': 'S1', 'start_date': '2011-06-18', 'end_date': '2011-06-21'}]}
            return SimpleNamespace(text='var t_data = ' + json.dumps(page) + ';')
        def get_json(self, url):
            if '/tr/149.' in url:
                self._call(url)
                return [{'roundID': '342', 'name': '分组', 'round_son': []}]
            if '/tr_round/p_342.' in url:
                self._call(url)
                return [{'matchID': '8905', 'match_date': '2012-10-05', 'match_time': '01:00', 'status': '2', 'is_publist': 1}]
            return super().get_json(url)
        def get_result_list(self, sid):
            self._call(f'resultlist/{sid}')
            return {'code': 200, 'data': [{'resultID': '66845' if sid == 20674 else '18691'}]}
        def get_result(self, rid):
            payload = super().get_result(rid)
            payload['data']['resultID'] = rid
            payload['data']['max_mvp']['match_id'] = '20674' if rid == 66845 else '8905'
            payload['data']['max_beiguo']['match_id'] = payload['data']['max_mvp']['match_id']
            return payload
    first = TwoTournaments(result, budget=5)
    report, code = run(first, tmp_path)
    assert code == 4 and report['imported'] == 1
    assert db.session.query(Match).one().date.year == 2012
    assert db.session.get(HistoryTournament, 333).status == 'queued'
    second = TwoTournaments(result, budget=4)
    report, code = run(second, tmp_path)
    assert code == 0 and report['imported'] == 1
    assert second.calls[0].endswith('/tr/333.json')
    assert not any('/149.' in url or '18691' in url or '8905' in url for url in second.calls)
    assert {match.date.year for match in db.session.query(Match)} == {2011, 2012}
    assert db.session.query(Player).count() == 20


@pytest.mark.parametrize('phase', ['all', 'discover'])
def test_recent_catalog_is_read_first_and_unknown_dates_remain_last(db, result, tmp_path, phase):
    for tid, start in ((719, datetime(2024, 6, 12).date()), (973, datetime(2026, 4, 1).date()), (1, None)):
        db.session.add(HistoryTournament(tournament_id=tid, name=str(tid), start_date=start,
                                         status='queued', last_seen_at=utc_now()))
    db.session.commit()

    class EmptyRounds(HistoricalSource):
        def get_json(self, url):
            self._call(url)
            assert '/tr/' in url
            return []

    client = EmptyRounds(result)
    report, code = run(client, tmp_path, phase=phase)
    assert code == 0 and client.calls == [f'https://img.scoregg.com/tr/{tid}.json' for tid in (973, 719, 1)]
    assert report['details']['coverage']['has_runnable_work'] is False


def test_recent_tournament_unfinished_results_series_and_stage_precede_older_catalog(db):
    db.session.add_all([
        HistoryTournament(tournament_id=719, name='old', start_date=datetime(2024, 6, 12).date(), status='queued'),
        HistoryTournament(tournament_id=973, name='recent', start_date=datetime(2026, 4, 1).date(), status='discovered'),
    ])
    db.session.flush()
    stage = HistoryStage(tournament_id=973, cache_key='p_973', parent_round_id=973, status='queued')
    db.session.add(stage)
    db.session.flush()
    series = HistorySeries(series_id=9730, tournament_id=973, stage_id=stage.id,
                           scheduled_at=datetime(2026, 5, 1), status='queued')
    task = SyncTask(task_key='result:97300', result_id=97300, series_id=9730, tournament_id=973,
                    scheduled_at=series.scheduled_at, status='queued')
    db.session.add_all([series, task])
    db.session.commit()
    assert history._next_all(5) == ('result', task)
    task.status = 'source_incomplete'
    db.session.commit()
    assert history._next_all(5) == ('series', series)
    series.status = 'discovered'
    db.session.commit()
    assert history._next_all(5) == ('stage', stage)
    stage.status = 'discovered'
    db.session.commit()
    assert history._next_all(5) == ('tournament', db.session.get(HistoryTournament, 719))


def test_recent_priority_keeps_exhausted_and_backoff_ineligible_without_retry_spin(db, result, tmp_path):
    tomorrow = utc_now() + timedelta(days=1)
    exhausted = HistoryTournament(tournament_id=973, name='exhausted', start_date=datetime(2026, 4, 1).date(),
                                  status='failed', failure_count=5, attempts=5, last_seen_at=utc_now())
    waiting = HistoryTournament(tournament_id=927, name='waiting', start_date=datetime(2026, 1, 1).date(),
                                status='failed', failure_count=2, attempts=2, next_retry_at=tomorrow,
                                last_seen_at=utc_now())
    old = HistoryTournament(tournament_id=719, name='old', start_date=datetime(2024, 6, 12).date(),
                            status='queued', last_seen_at=utc_now())
    db.session.add_all([exhausted, waiting, old])
    db.session.commit()
    assert history._next_all(5) == ('tournament', old)
    old.status = 'discovered'
    db.session.commit()
    before = [(tour.status, tour.failure_count, tour.attempts, tour.next_retry_at) for tour in (exhausted, waiting)]
    assert history._next_all(5) == (None, None)
    client = HistoricalSource(result)
    report, code = run(client, tmp_path)
    assert code == 2 and report['status'] == 'waiting_retry' and client.calls == []
    assert [(tour.status, tour.failure_count, tour.attempts, tour.next_retry_at) for tour in (exhausted, waiting)] == before
    assert report['details']['coverage']['has_runnable_work'] is False
    assert report['details']['coverage']['failed_tasks'] == 2


@pytest.mark.parametrize('phase', ['all', 'fetch'])
def test_unmapped_results_use_recent_schedule_first_without_refetching_terminal_rows(db, result, tmp_path, phase):
    db.session.add(HistoryTournament(tournament_id=973, name='catalog already read',
                                     status='discovered', last_seen_at=utc_now()))
    db.session.add_all([
        SyncTask(task_key='result:5', result_id=5, scheduled_at=datetime(2024, 6, 12), status='queued'),
        SyncTask(task_key='result:55', result_id=55, scheduled_at=datetime(2026, 4, 1), status='queued'),
        SyncTask(task_key='result:1', result_id=1, scheduled_at=None, status='queued'),
        SyncTask(task_key='result:998', result_id=998, scheduled_at=datetime(2026, 5, 1), status='imported'),
        SyncTask(task_key='result:999', result_id=999, scheduled_at=datetime(2026, 5, 1), status='source_incomplete'),
    ])
    db.session.commit()

    class NonLOL(HistoricalSource):
        def get_result(self, rid):
            self._call(f'result/{rid}')
            return {'code': 200, 'data': {'gameID': '2', 'resultID': rid}}

    client = NonLOL(result)
    assert run(client, tmp_path, phase=phase)[1] == 0
    assert client.calls == ['result/55', 'result/5', 'result/1']
    assert db.session.query(SyncTask).filter_by(result_id=998).one().status == 'imported'
    assert db.session.query(SyncTask).filter_by(result_id=999).one().status == 'source_incomplete'


def test_discover_resultlists_use_recent_schedule_then_unknown_without_guessing_missing_ids(db, result, tmp_path):
    db.session.add(HistoryTournament(tournament_id=973, name='recent', status='discovered', last_seen_at=utc_now()))
    db.session.flush()
    stage = HistoryStage(tournament_id=973, cache_key='p_973', parent_round_id=973, status='discovered')
    db.session.add(stage)
    db.session.flush()
    for sid, date in ((5, datetime(2024, 6, 12)), (55, datetime(2026, 4, 1)), (1, None)):
        db.session.add(HistorySeries(series_id=sid, tournament_id=973, stage_id=stage.id,
                                     scheduled_at=date, source_status='2', is_publist=1, status='queued'))
    db.session.commit()

    class EmptyResults(HistoricalSource):
        def get_result_list(self, sid):
            self._call(f'resultlist/{sid}')
            return {'code': 200, 'data': []}

    client = EmptyResults(result)
    report, code = run(client, tmp_path, phase='discover')
    assert code == 0 and client.calls == ['resultlist/55', 'resultlist/5', 'resultlist/1']
    assert db.session.query(HistorySeries).filter_by(status='pending').count() == 3
    assert db.session.query(SyncTask).count() == 0
    assert report['details']['coverage']['complete_available'] is False


def test_exhausted_failure_stays_visible_without_past_retry_spin(db, result, tmp_path):
    run(HistoricalSource(result, resultlist_error=True), tmp_path)
    series = db.session.query(HistorySeries).one()
    series.failure_count, series.next_retry_at = 5, utc_now() - timedelta(seconds=1)
    db.session.commit()
    coverage = coverage_report()
    assert coverage['exhausted_tasks'] == 1 and coverage['failed_tasks'] == 1
    assert coverage['next_retry_at'] is None and coverage['has_runnable_work'] is False
    assert coverage['snapshot_completed'] is False
    assert run(HistoricalSource(result), tmp_path)[0]['status'] == 'waiting_retry'


def test_known_unmapped_legacy_ids_are_checked_and_nonlol_cannot_survive(db, result, tmp_path):
    db.session.add(Match(match_id=42, source='legacy', verified=False))
    db.session.commit()
    class KnownNonLOL(HistoricalSource):
        def get_result(self, rid):
            assert rid == 42
            payload = super().get_result(rid)
            payload['data']['gameID'] = '2'
            return payload
    source = KnownNonLOL(result, pub=0)
    report, code = run(source, tmp_path)
    assert code == 0 and 'result/42' in source.calls
    assert db.session.query(Match).count() == 0
    assert db.session.query(SyncTask).one().status == 'skipped'
    assert (tmp_path / 'raw' / 'scoregg' / '42.json').is_file()
    assert report['details']['coverage']['counts']['known_unmapped_results']['skipped'] == 1


@pytest.mark.parametrize('cached', [False, True])
def test_unmapped_finished_legacy_partial_keeps_reliable_rows_without_refetch_or_guessed_identity(
        db, legacy_partial_result, tmp_path, cached):
    db.session.add(Match(match_id=18894, source='legacy', verified=False, game_time=999))
    db.session.add_all([
        Team(match_id=18894, team_name='LM', game_time=999, attack=777),
        Team(match_id=18894, team_name='PE', player_c_id='CSV guessed identity'),
        Team(match_id=18894, team_name='obsolete team'),
        Player(match_id=18894, team_name='LM', position='a', name='CSV stale name', kills=99,
               atk=888, pic='CSV stale picture', game_time=999),
        Player(match_id=18894, team_name='PE', position='c', name='CSV guessed identity'),
        Player(match_id=18894, team_name='obsolete team', position='wrong', name='obsolete player'),
    ])
    db.session.commit()
    assert history._seed_known_legacy() == 1
    task = db.session.query(SyncTask).one()
    assert task.series_id is None
    source = HistoricalSource(legacy_partial_result)
    raw = tmp_path / 'raw' / 'scoregg' / '18894.json'
    before = copy.deepcopy(legacy_partial_result)
    if cached:
        raw.parent.mkdir(parents=True)
        raw.write_text(json.dumps(legacy_partial_result), encoding='utf-8')
    outcome = history._fetch_task(source, task, tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == 'source_incomplete' and outcome['reused_raw'] is cached
    assert source.calls == ([] if cached else ['result/18894'])
    assert legacy_partial_result == before and json.loads(raw.read_text(encoding='utf-8')) == before
    match = db.session.query(Match).one()
    assert match.source == 'scoregg' and match.verified and match.game_time is None
    assert match.win_team_name == 'PE' and match.date_source == 'updated_at'
    assert match.date == datetime(2022, 3, 9, 18, 59, 28)  # 只存源更新时间，绝不冒充赛程或赛年。
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 9
    player = db.session.query(Player).filter_by(team_name='LM', position='a').one()
    assert player.name == 'Yao' and player.kills == 0 and player.kda == 1.4
    assert player.atk is None and player.pic is None and player.game_time is None
    assert db.session.query(Player).filter_by(team_name='PE', position='c').count() == 0
    assert db.session.query(Team).filter_by(team_name='PE').one().player_c_id is None
    assert all(team.attack is None and team.money is None for team in db.session.query(Team))
    assert all(player.atk is None and player.money is None and player.hits is None for player in db.session.query(Player))
    assert task.failure_count == 0 and task.next_retry_at is None
    assert history._next_all(max_attempts=5) == (None, None)
    identities = {(player.team_name, player.position): player.id for player in db.session.query(Player)}
    assert ingest_result(before, 18894, allow_incomplete=True).status == 'source_incomplete'
    assert {(player.team_name, player.position): player.id for player in db.session.query(Player)} == identities
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 9
    coverage = coverage_report()
    assert coverage['complete_available'] is False
    assert coverage['counts']['known_unmapped_results'] == {'source_incomplete': 1}
    assert coverage['legacy']['unverified_matches'] == 0


def test_unmapped_legacy_missing_name_with_valid_duration_is_saved_as_partial(db, legacy_partial_result, tmp_path):
    legacy_partial_result['data']['result_list'].update(game_time_m='30', game_time_s='00')
    db.session.add(Match(match_id=18894, source='legacy', verified=False))
    db.session.commit()
    history._seed_known_legacy()
    source = HistoricalSource(legacy_partial_result)
    outcome = history._fetch_task(source, db.session.query(SyncTask).one(), tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == 'source_incomplete'
    assert db.session.query(Match).one().game_time == 1800
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 9


@pytest.mark.parametrize('case,expected', [
    ('unknown_winner', 'pending'), ('both_winners', 'pending'), ('missing_gameID', 'failed'),
    ('non_lol', 'skipped'), ('bad_response', 'failed'), ('empty_detail', 'pending'),
    ('wrong_result_id', 'failed'), ('wrong_winner_id', 'pending'), ('missing_winner_id', 'pending'),
    ('contradictory_kills', 'pending'),
])
def test_unmapped_legacy_partial_requires_source_lol_and_finished_evidence(db, legacy_partial_result, tmp_path, case, expected):
    data = legacy_partial_result['data']
    info = data['result_list']
    if case == 'unknown_winner':
        info['blue_result'] = '0'
    elif case == 'both_winners':
        info['red_result'] = '1'
    elif case == 'missing_gameID':
        del data['gameID']
    elif case == 'non_lol':
        data['gameID'] = '2'
    elif case == 'bad_response':
        legacy_partial_result['code'] = 500
    elif case == 'empty_detail':
        legacy_partial_result['data'] = {}
    elif case == 'wrong_result_id':
        data['resultID'] = '18895'
    elif case == 'wrong_winner_id':
        info['win_teamID'] = info['red_teamID']
    elif case == 'missing_winner_id':
        del info['win_teamID']
    elif case == 'contradictory_kills':
        info['blue_kill'] = '30'
    db.session.add(Match(match_id=18894, source='legacy', verified=False))
    db.session.commit()
    history._seed_known_legacy()
    source = HistoricalSource(legacy_partial_result)
    outcome = history._fetch_task(source, db.session.query(SyncTask).one(), tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == expected and outcome['status'] != 'source_incomplete'
    assert db.session.query(Team).count() == 0 and db.session.query(Player).count() == 0
    if expected == 'skipped':
        assert db.session.query(Match).count() == 0
    else:
        match = db.session.query(Match).one()
        assert match.source == 'legacy' and match.verified is False


def test_unmapped_arbitrary_task_does_not_gain_legacy_partial_permission(db, legacy_partial_result, tmp_path):
    db.session.add(SyncTask(task_key='result:18894', result_id=18894))
    db.session.commit()
    outcome = history._fetch_task(HistoricalSource(legacy_partial_result), db.session.query(SyncTask).one(),
                                  tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == 'pending' and db.session.query(Match).count() == 0


@pytest.mark.parametrize('source_name,verified', [('scoregg', False), ('scoregg', True), ('legacy', True)])
def test_existing_nonlegacy_or_verified_match_does_not_gain_unmapped_partial_permission(
        db, legacy_partial_result, tmp_path, source_name, verified):
    db.session.add(Match(match_id=18894, source=source_name, verified=verified, game_time=999))
    db.session.add(SyncTask(task_key='result:18894', result_id=18894))
    db.session.commit()
    outcome = history._fetch_task(HistoricalSource(legacy_partial_result), db.session.query(SyncTask).one(),
                                  tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == 'pending'
    match = db.session.query(Match).one()
    assert match.source == source_name and match.verified is verified and match.game_time == 999


@pytest.mark.parametrize('fresh_finished', [False, True])
def test_unmapped_partial_permission_is_recomputed_for_fresh_response(db, legacy_partial_result, tmp_path, fresh_finished):
    cached = copy.deepcopy(legacy_partial_result)
    fresh = copy.deepcopy(legacy_partial_result)
    if fresh_finished:
        cached['data']['result_list']['blue_result'] = '0'
    else:
        # 缓存有明确胜方但无法规范化；它的放宽资格不能泄漏给新取的未结束响应。
        cached['data']['result_list']['red_star_a_kda'] = '-1'
        fresh['data']['result_list']['blue_result'] = '0'
    raw = tmp_path / 'raw' / 'scoregg' / '18894.json'
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(cached), encoding='utf-8')
    db.session.add(Match(match_id=18894, source='legacy', verified=False))
    db.session.commit()
    history._seed_known_legacy()
    source = HistoricalSource(fresh)
    outcome = history._fetch_task(source, db.session.query(SyncTask).one(), tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == ('source_incomplete' if fresh_finished else 'pending')
    assert outcome['reused_raw'] is False and source.calls == ['result/18894']
    assert db.session.query(Player).count() == (9 if fresh_finished else 0)


@pytest.mark.parametrize('kills_state', ['missing_one', 'missing_all', 'zero_all'])
def test_unmapped_finished_legacy_can_keep_partial_with_missing_or_zero_kills(db, legacy_partial_result, tmp_path, kills_state):
    info = legacy_partial_result['data']['result_list']
    if kills_state == 'missing_one':
        del info['red_star_a_kills']
    else:
        for side in ('red', 'blue'):
            fields = [f'{side}_kill'] + [f'{side}_star_{position}_kills' for position in 'abcde']
            for field in fields:
                if kills_state == 'zero_all':
                    info[field] = '0'
                else:
                    del info[field]
    db.session.add(Match(match_id=18894, source='legacy', verified=False))
    db.session.commit()
    history._seed_known_legacy()
    outcome = history._fetch_task(HistoricalSource(legacy_partial_result), db.session.query(SyncTask).one(),
                                  tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == 'source_incomplete'
    match = db.session.query(Match).one()
    assert match.verified and match.win_team_name == 'PE' and match.game_time is None
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 9
    player = db.session.query(Player).filter_by(team_name='LM', position='a').one()
    assert player.kills == (0 if kills_state == 'zero_all' else None)


@pytest.mark.parametrize('days_ago', [-1, 1, 14])
def test_unmapped_legacy_with_recent_or_future_known_schedule_stays_strict(db, legacy_partial_result, tmp_path, days_ago):
    now = datetime(2026, 10, 3)
    db.session.add(Match(match_id=18894, source='legacy', verified=False))
    db.session.commit()
    history._seed_known_legacy()
    task = db.session.query(SyncTask).one()
    task.scheduled_at = now - timedelta(days=days_ago)
    db.session.commit()
    outcome = history._fetch_task(HistoricalSource(legacy_partial_result), task, tmp_path / 'raw', None, now)
    assert outcome['status'] == 'pending' and db.session.query(Match).one().verified is False


@pytest.mark.parametrize('source_status,days_ago,expected', [
    ('2', 15, 'source_incomplete'), ('2', None, 'source_incomplete'),
    ('2', 14, 'pending'), ('2', 1, 'pending'), ('2', -1, 'pending'),
    ('1', 30, 'pending'), ('0', 30, 'pending'),
])
def test_known_series_keeps_existing_age_and_live_constraints(db, legacy_partial_result, tmp_path, source_status, days_ago, expected):
    now = datetime(2026, 10, 3)
    db.session.add(HistoryTournament(tournament_id=333, name='fixture tournament'))
    db.session.commit()
    stage = HistoryStage(tournament_id=333, cache_key='p_765', parent_round_id=765)
    db.session.add(stage)
    db.session.flush()
    db.session.add(HistorySeries(series_id=9057, tournament_id=333, stage_id=stage.id,
                                 source_status=source_status, is_publist=1,
                                 scheduled_at=None if days_ago is None else now - timedelta(days=days_ago)))
    db.session.add(Match(match_id=18894, source='legacy', verified=False))
    db.session.commit()
    history._seed_known_legacy()
    task = db.session.query(SyncTask).one()
    task.series_id = 9057
    db.session.commit()
    outcome = history._fetch_task(HistoricalSource(legacy_partial_result), task, tmp_path / 'raw', None, now)
    assert outcome['status'] == expected


def test_unmapped_partial_transaction_failure_preserves_existing_business_rows(db, legacy_partial_result, tmp_path, monkeypatch):
    db.session.add(Match(match_id=18894, source='legacy', verified=False, game_time=999))
    db.session.add(Player(match_id=18894, team_name='LM', position='a', name='CSV name', kills=99))
    db.session.commit()
    history._seed_known_legacy()
    original_upsert = ingestion.bulk_upsert

    def fail_player_write(model, rows, keys, **kwargs):
        if model is Player:
            raise IntegrityError('fixture player write', {}, Exception('fixture transaction failure'))
        return original_upsert(model, rows, keys, **kwargs)

    monkeypatch.setattr(ingestion, 'bulk_upsert', fail_player_write)
    outcome = history._fetch_task(HistoricalSource(legacy_partial_result), db.session.query(SyncTask).one(),
                                  tmp_path / 'raw', None, datetime(2026, 10, 3))
    assert outcome['status'] == 'failed'
    match = db.session.query(Match).one()
    assert match.source == 'legacy' and match.verified is False and match.game_time == 999
    assert db.session.query(Team).count() == 0 and db.session.query(Player).one().kills == 99


def test_unmapped_source_incomplete_prevents_complete_claim(db, result, tmp_path):
    run(HistoricalSource(result), tmp_path)
    db.session.add(SyncTask(task_key='result:42', result_id=42, status='source_incomplete'))
    db.session.commit()
    coverage = coverage_report()
    assert coverage['snapshot_completed'] is True and coverage['complete_available'] is False


def test_stage_conflict_rolls_back_partial_discovery_and_keeps_raw(db, result, tmp_path):
    class DuplicateSeries(HistoricalSource):
        def get_json(self, url):
            rows = super().get_json(url)
            return rows * 2 if '/tr_round/' in url else rows
    report, code = run(DuplicateSeries(result), tmp_path)
    assert code == 2 and db.session.query(HistoryStage).one().status == 'failed'
    assert db.session.query(HistorySeries).count() == 0
    assert (tmp_path / 'raw' / 'history' / 'stages' / '333' / 'p_765.json').is_file()


def test_result_id_in_two_series_is_reported_without_overwriting_good_association(db, result, tmp_path):
    class ConflictingResults(HistoricalSource):
        def get_json(self, url):
            rows = super().get_json(url)
            if '/tr_round/' in url:
                # 先建立有效关联，再发现更早系列的重复声明；跨系列覆盖仍须拒绝。
                second = dict(rows[0], matchID='20709', match_time='15:45')
                rows.append(second)
            return rows
    report, code = run(ConflictingResults(result), tmp_path)
    assert code == 2 and db.session.query(Match).count() == 1
    assert db.session.query(Match).one().series_id == 20674
    assert db.session.get(HistorySeries, 20709).status == 'failed'
    assert '两个' in db.session.get(HistorySeries, 20709).last_error


def test_full_raw_removes_same_team_legacy_rows_with_invalid_positions(db, result, tmp_path):
    ingest_result(result, 66845)
    db.session.add(Player(match_id=66845, team_name='LGD', position='wrong', name='旧错误位置'))
    db.session.commit()
    assert db.session.query(Player).count() == 11
    report, code = run(HistoricalSource(result), tmp_path)
    assert code == 0 and db.session.query(Player).count() == 10
    assert report['details']['coverage']['counts']['results']['complete'] == 1


def test_partial_cached_raw_still_updates_corrected_schedule_without_refetch(db, result, tmp_path):
    result['data']['result_list']['game_time_m'] = result['data']['result_list']['game_time_s'] = '0'
    run(HistoricalSource(result), tmp_path)
    series = db.session.query(HistorySeries).one()
    db.session.query(HistoryStage).one().status = 'queued'
    db.session.commit()
    class CorrectedDate(HistoricalSource):
        def get_json(self, url):
            rows = super().get_json(url)
            if '/tr_round/' in url:
                rows[0]['match_date'] = '2011-06-19'
            return rows
    source = CorrectedDate(result)
    report, code = run(source, tmp_path)
    assert code == 0 and db.session.query(Match).one().date.day == 19
    assert 'result/66845' not in source.calls
    assert report['details']['coverage']['counts']['results']['source_incomplete'] == 1


def test_first_legacy_verification_clears_metrics_absent_from_public_partial_source(db, result, tmp_path):
    # 独立旧 CSV 证据不得被新 gameID 的核验标签连带升级。
    db.session.add(Match(match_id=66845, source='legacy', verified=False, game_time=999))
    db.session.add(Player(match_id=66845, team_name='LGD', position='a', name='旧名字', kills=99, atk=88,
                          game_time=999, pic='legacy-picture'))
    db.session.add(Team(match_id=66845, team_name='LGD', game_time=999, attack=777))
    db.session.commit()
    info = result['data']['result_list']
    info['game_time_m'] = info['game_time_s'] = '0'
    for field in ('red_star_a_kills', 'red_star_a_atk_o', 'red_star_a_pic', 'red_attack'):
        info.pop(field, None)
    report, code = run(HistoricalSource(result), tmp_path)
    assert code == 0
    match = db.session.query(Match).one()
    player = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    team = db.session.query(Team).filter_by(team_name='LGD').one()
    assert match.verified is True and match.source == 'scoregg' and match.game_time is None
    assert player.kills is None and player.atk is None and player.pic is None and player.game_time is None
    assert team.game_time is None and team.attack is None
    assert db.session.query(SyncTask).one().status == 'source_incomplete'


def test_complete_first_verification_also_clears_unverified_optional_fields(db, result, tmp_path):
    db.session.add(Match(match_id=66845, source='scoregg', verified=False))
    db.session.add(Player(match_id=66845, team_name='LGD', position='a', name='旧名字', atk=99, pic='legacy-picture'))
    db.session.add(Team(match_id=66845, team_name='LGD', attack=777))
    db.session.commit()
    info = result['data']['result_list']
    for field in ('red_star_a_atk_o', 'red_star_a_pic', 'red_attack'):
        info.pop(field, None)
    outcome = ingest_result(result, 66845)
    assert outcome.status == 'imported'
    player = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    assert player.atk is None and player.pic is None
    assert db.session.query(Team).filter_by(team_name='LGD').one().attack is None


def test_optional_metrics_from_previously_verified_source_remain_protected(db, result, tmp_path):
    assert ingest_result(result, 66845).status == 'imported'
    old = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    attack, picture = old.atk, old.pic
    for field in ('red_star_a_atk_o', 'red_star_a_pic'):
        result['data']['result_list'].pop(field, None)
    assert ingest_result(result, 66845).status == 'imported'
    updated = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    assert updated.atk == attack and updated.pic == picture


def test_raw_replay_corrects_previously_promoted_metrics_and_keeps_true_schedule(db, result, tmp_path):
    schedule = {'series_id': 20674, 'tournament_id': 333, 'tournament_name': 'S1',
                'scheduled_at': datetime(2011, 6, 18, 16, 30)}
    ingest_result(result, 66845, schedule)
    player = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    player.kills, player.pic = 99, 'old-unverified-picture'
    db.session.query(Match).one().game_time = 999
    db.session.commit()
    info = result['data']['result_list']
    info['game_time_m'] = info['game_time_s'] = '0'
    info.pop('red_star_a_kills')
    info.pop('red_star_a_pic')
    outcome = ingest_result(result, 66845, schedule, allow_incomplete=True, replace_existing=True)
    assert outcome.status == 'source_incomplete'
    assert db.session.query(Match).one().game_time is None
    assert db.session.query(Match).one().date.year == 2011
    assert db.session.query(Match).one().tournament_id == 333
    repaired = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    assert repaired.kills is None and repaired.pic is None


def test_raw_repair_audits_without_mutation_then_rebuilds_with_hash_evidence(db, result, tmp_path):
    run(HistoricalSource(result), tmp_path)
    info = result['data']['result_list']
    info['game_time_m'] = info['game_time_s'] = '0'
    info.pop('red_star_a_kills')
    raw = tmp_path / 'raw' / 'scoregg' / '66845.json'
    raw.write_text(json.dumps(result), encoding='utf-8')
    match = db.session.query(Match).one()
    match.game_time = 999
    player = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    player.kills = 99
    db.session.commit()
    audit = repair_verified_raw(tmp_path / 'raw', tmp_path / 'reports')
    assert audit['request_count'] == 0 and audit['changed_records'] == 1 and audit['applied'] == 0
    assert db.session.query(Match).one().game_time == 999
    assert audit['records'][0]['sha256'] and audit['cleared_unsupported_fields'] >= 2
    repaired = repair_verified_raw(tmp_path / 'raw', tmp_path / 'reports', apply=True)
    assert repaired['applied'] == 1 and repaired['blocked'] == 0 and repaired['failed'] == 0
    assert db.session.query(Match).one().game_time is None
    assert db.session.query(Match).one().date.year == 2011
    assert db.session.query(Match).one().tournament_id == 333
    assert db.session.query(Player).filter_by(team_name='LGD', position='a').one().kills is None
    assert db.session.query(SyncTask).one().status == 'source_incomplete'
    repeat = repair_verified_raw(tmp_path / 'raw', tmp_path / 'reports')
    assert repeat['changed_records'] == 0 and repeat['changed_fields'] == 0


def test_raw_repair_reports_missing_or_nonlol_evidence_and_preserves_verified_records(db, result, tmp_path):
    ingest_result(result, 66845)
    audit = repair_verified_raw(tmp_path / 'raw', tmp_path / 'reports', apply=True)
    assert audit['blocked'] == 1 and audit['applied'] == 0
    assert db.session.query(Match).one().verified is True
    raw = tmp_path / 'raw' / 'scoregg' / '66845.json'
    raw.parent.mkdir(parents=True)
    result['data']['gameID'] = '2'
    raw.write_text(json.dumps(result), encoding='utf-8')
    audit = repair_verified_raw(tmp_path / 'raw', tmp_path / 'reports', apply=True)
    assert audit['blocked'] == 1 and audit['applied'] == 0
    assert db.session.query(Match).count() == 1 and db.session.query(Player).count() == 10


@pytest.mark.parametrize('elapsed,expected_requests', [
    (timedelta(hours=24) - timedelta(microseconds=1), 0),
    (timedelta(hours=24), 1),
    (timedelta(hours=24) + timedelta(microseconds=1), 1),
])
def test_catalog_refresh_24_hour_utc_boundary_keeps_successful_prefix(db, result, tmp_path, monkeypatch,
                                                                    elapsed, expected_requests):
    first_seen = datetime(2026, 10, 3, 9)
    monkeypatch.setattr(history, 'utc_now', lambda: first_seen)
    history._seed_catalog(HistoricalSource(result), tmp_path / 'raw')
    tour = db.session.get(HistoryTournament, 333)
    tour.status, tour.next_retry_at = 'discovered', first_seen + timedelta(days=2)
    stage = HistoryStage(tournament_id=333, cache_key='p_765', parent_round_id=765, status='discovered')
    db.session.add(stage)
    db.session.flush()
    db.session.add(HistorySeries(series_id=20674, tournament_id=333, stage_id=stage.id, status='discovered'))
    db.session.commit()
    monkeypatch.setattr(history, 'utc_now', lambda: first_seen + elapsed)
    source = HistoricalSource(result)
    history._seed_catalog(source, tmp_path / 'raw')
    assert len(source.calls) == expected_requests
    assert tour.status == 'discovered' and tour.next_retry_at == first_seen + timedelta(days=2)
    assert stage.status == 'discovered' and db.session.get(HistorySeries, 20674).status == 'discovered'
    assert tour.last_seen_at == (first_seen + elapsed if expected_requests else first_seen)
    next_batch = HistoricalSource(result)
    assert history._seed_catalog(next_batch, tmp_path / 'raw') == 0 and next_batch.calls == []


def test_catalog_daily_refresh_adds_new_tournament_without_resetting_old_progress(db, result, tmp_path, monkeypatch):
    first_seen = datetime(2026, 10, 3, 9)
    monkeypatch.setattr(history, 'utc_now', lambda: first_seen)
    history._seed_catalog(HistoricalSource(result), tmp_path / 'raw')
    old = db.session.get(HistoryTournament, 333)
    old.status, old.stage_count = 'discovered', 3
    db.session.commit()
    class NewCatalog(HistoricalSource):
        def get(self, url):
            response = super().get(url)
            page, _ = json.JSONDecoder().raw_decode(response.text.split(' = ', 1)[1])
            page['tournament_list'].append({'tournamentID': '149', 'name': 'S2',
                                            'start_date': '2012-10-04', 'end_date': '2012-10-14'})
            response.text = 'var t_data = ' + json.dumps(page) + ';'
            return response
    monkeypatch.setattr(history, 'utc_now', lambda: first_seen + timedelta(hours=24))
    source = NewCatalog(result)
    assert history._seed_catalog(source, tmp_path / 'raw') == 2 and len(source.calls) == 1
    assert db.session.get(HistoryTournament, 149).status == 'queued'
    assert old.status == 'discovered' and old.stage_count == 3
    assert old.last_seen_at == db.session.get(HistoryTournament, 149).last_seen_at == first_seen + timedelta(hours=24)
    next_batch = NewCatalog(result)
    history._seed_catalog(next_batch, tmp_path / 'raw')
    assert next_batch.calls == []


def test_catalog_cache_age_uses_latest_seen_timestamp(db, result, tmp_path, monkeypatch):
    checked_at = datetime(2026, 10, 3, 9)
    monkeypatch.setattr(history, 'utc_now', lambda: checked_at)
    db.session.add_all([
        HistoryTournament(tournament_id=333, name='旧归档', status='discovered',
                          last_seen_at=checked_at - timedelta(days=10)),
        HistoryTournament(tournament_id=149, name='最近目录项', status='discovered',
                          last_seen_at=checked_at - timedelta(hours=1)),
    ])
    db.session.commit()
    source = HistoricalSource(result)
    assert history._seed_catalog(source, tmp_path / 'raw') == 0 and source.calls == []


def test_catalog_daily_refresh_requeues_only_changed_existing_entry(db, result, tmp_path, monkeypatch):
    checked_at = datetime(2026, 10, 3, 9)
    monkeypatch.setattr(history, 'utc_now', lambda: checked_at)
    history._seed_catalog(HistoricalSource(result), tmp_path / 'raw')
    changed = db.session.get(HistoryTournament, 333)
    changed.status = 'discovered'
    archived = HistoryTournament(tournament_id=149, name='目录未再列出但保留的归档', status='discovered',
                                 last_seen_at=checked_at)
    db.session.add(archived)
    db.session.commit()
    class CorrectedCatalog(HistoricalSource):
        def get(self, url):
            response = super().get(url)
            page, _ = json.JSONDecoder().raw_decode(response.text.split(' = ', 1)[1])
            page['tournament_list'][0]['name'] = '官网更正赛事名称'
            response.text = 'var t_data = ' + json.dumps(page) + ';'
            return response
    monkeypatch.setattr(history, 'utc_now', lambda: checked_at + timedelta(hours=24))
    source = CorrectedCatalog(result)
    history._seed_catalog(source, tmp_path / 'raw')
    assert len(source.calls) == 1
    assert changed.name == '官网更正赛事名称' and changed.status == 'queued'
    assert archived.status == 'discovered' and archived.last_seen_at == checked_at


@pytest.mark.parametrize('source_field,target,value', [
    ('blue_star_a_part', 'part', '125'),
    ('red_star_c_part', 'part', '146.15'),
    ('red_star_d_part', 'part', '108.33'),
    ('red_star_a_atk_p', 'atk_p', '-1'),
    ('red_star_a_def_p', 'def_p', 'broken'),
])
def test_historical_invalid_optional_percentage_is_null_with_original_reason(db, result, tmp_path,
                                                                           source_field, target, value):
    result['data']['result_list'][source_field] = value
    report, code = run(HistoricalSource(result), tmp_path)
    assert code == 0
    side, _, position, *_ = source_field.split('_')
    team_name = result['data']['result_list'][side + '_name']
    player = db.session.query(Player).filter_by(team_name=team_name, position=position).one()
    assert getattr(player, target) is None
    assert db.session.query(Player).count() == 10 and db.session.query(Team).count() == 2
    task = db.session.query(SyncTask).one()
    assert task.status == 'source_incomplete' and task.failure_count == 0 and task.next_retry_at is None
    assert source_field in task.last_error and value in task.last_error
    assert report['details']['coverage']['counts']['results'].get('complete', 0) == 0
    assert json.loads((tmp_path / 'raw' / 'scoregg' / '66845.json').read_text(encoding='utf-8'))['data']['result_list'][source_field] == value
    repeat = HistoricalSource(result)
    assert run(repeat, tmp_path)[1] == 0 and repeat.calls == []


def test_historical_invalid_percentage_overrides_verified_old_value_only(db, result, tmp_path):
    assert ingest_result(result, 66845).status == 'imported'
    player = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    player.part = 150
    valid_photo = player.pic
    valid_attack = player.atk
    db.session.commit()
    info = result['data']['result_list']
    info['red_star_a_part'] = '125'
    info.pop('red_star_a_pic')
    info.pop('red_star_a_atk_o')
    outcome = ingest_result(result, 66845, allow_incomplete=True)
    assert outcome.status == 'source_incomplete'
    player = db.session.query(Player).filter_by(team_name='LGD', position='a').one()
    assert player.part is None and player.pic == valid_photo and player.atk == valid_attack
    assert 'red_star_a_part' in outcome.error and '125' in outcome.error


def test_strict_daily_still_rejects_invalid_percentage_and_historical_structure_remains_strict(db, result, tmp_path):
    result['data']['result_list']['red_star_a_part'] = '125'
    assert ingest_result(result, 66845).status == 'failed'
    assert db.session.query(Match).count() == 0
    result['data']['result_list'].pop('blue_star_e_name')
    assert ingest_result(result, 66845, allow_incomplete=True).status == 'source_incomplete'
    assert db.session.query(Match).count() == 1 and db.session.query(Player).count() == 9
    result['data']['result_list']['blue_star_e_name'] = 'restored'
    result['data']['result_list']['red_star_a_kills'] = '-1'
    assert ingest_result(result, 66845, allow_incomplete=True).status == 'failed'
    assert db.session.query(Match).count() == 1


def test_failed_historical_percentage_recovery_reuses_raw_without_network_or_retries(db, result, tmp_path):
    run(HistoricalSource(result), tmp_path)
    info = result['data']['result_list']
    info['blue_star_a_part'] = '125'
    raw = tmp_path / 'raw' / 'scoregg' / '66845.json'
    raw.write_text(json.dumps(result), encoding='utf-8')
    task = db.session.query(SyncTask).one()
    task.status, task.failure_count, task.next_retry_at = 'failed', 2, utc_now() - timedelta(seconds=1)
    db.session.commit()
    source = HistoricalSource(result)
    report, code = run(source, tmp_path)
    assert code == 0 and source.calls == []
    assert report['details']['outcomes'][0]['reused_raw'] is True
    assert task.status == 'source_incomplete' and task.failure_count == 0 and task.next_retry_at is None
    assert db.session.query(Player).filter_by(team_name='EDG', position='a').one().part is None
    again = HistoricalSource(result)
    assert run(again, tmp_path)[1] == 0 and again.calls == []


def test_explicit_catalog_refresh_still_requeues_all_discovered_children(db, result, tmp_path, monkeypatch):
    checked_at = datetime(2026, 10, 3, 9)
    monkeypatch.setattr(history, 'utc_now', lambda: checked_at)
    history._seed_catalog(HistoricalSource(result), tmp_path / 'raw')
    tour = db.session.get(HistoryTournament, 333)
    tour.status = 'discovered'
    stage = HistoryStage(tournament_id=333, cache_key='p_765', parent_round_id=765, status='discovered')
    db.session.add(stage)
    db.session.flush()
    db.session.add(HistorySeries(series_id=20674, tournament_id=333, stage_id=stage.id, status='discovered'))
    db.session.commit()
    source = HistoricalSource(result)
    history._seed_catalog(source, tmp_path / 'raw', refresh=True)
    assert len(source.calls) == 1 and tour.status == 'queued'
    assert stage.status == 'queued' and db.session.get(HistorySeries, 20674).status == 'queued'


@pytest.mark.parametrize('minutes,seconds', [('00', '01'), ('0', '0'), ('33', '60'), ('-1', '10'), ('bad', '10')])
def test_history_bad_or_placeholder_duration_clears_all_previous_source_values(db, result, minutes, seconds):
    assert ingest_result(result, 66845).status == 'imported'
    result['data']['result_list'].update(game_time_m=minutes, game_time_s=seconds)
    outcome = ingest_result(result, 66845, allow_incomplete=True)
    assert outcome.status == 'source_incomplete' and 'game_time' in outcome.error
    for model in (Match, Team, Player):
        assert all(row.game_time is None for row in db.session.query(model))
    assert db.session.query(Player).count() == 10 and db.session.query(Team).count() == 2
    task = db.session.query(SyncTask).one()
    assert task.failure_count == 0 and task.next_retry_at is None


@pytest.mark.parametrize('seconds,status', [('01', 'pending'), ('60', 'failed')])
def test_daily_duration_validation_remains_strict(db, result, seconds, status):
    result['data']['result_list'].update(game_time_m='00' if seconds == '01' else '33', game_time_s=seconds)
    assert ingest_result(result, 66845).status == status
    assert db.session.query(Match).count() == 0


@pytest.mark.parametrize('source,verified', [('legacy', False), ('scoregg', True)])
def test_history_missing_name_removes_previous_slot_and_team_name_reference(db, identity_result, source, verified):
    result = identity_result
    ingest_result(result, 66845)
    match = db.session.query(Match).one()
    match.source, match.verified = source, verified
    db.session.commit()
    result['data']['result_list']['blue_star_e_name'] = ''
    normalized = normalize_result(result, 66845, allow_incomplete=True)
    slot = normalized['missing_roster_slots'][0]
    assert slot['team_name'] == 'EDG' and slot['position'] == 'e'
    assert slot['source_player_id'] == '17863'
    outcome = ingest_result(result, 66845, allow_incomplete=True)
    assert outcome.status == 'source_incomplete'
    assert db.session.query(Match).one().verified is True
    assert db.session.query(Player).count() == 9
    assert db.session.query(Player).filter_by(team_name='EDG', position='e').count() == 0
    assert db.session.query(Team).filter_by(team_name='EDG').one().player_e_id is None


def _write_source_raw(tmp_path, result, result_id):
    raw = tmp_path / 'raw' / 'scoregg' / f'{result_id}.json'
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return raw


def test_source_name_index_recovers_by_unique_id_and_color_with_raw_sha_audit(db, identity_result, tmp_path):
    result = identity_result
    anchor = _write_source_raw(tmp_path, result, 66844)
    result['data']['result_list']['blue_star_e_name'] = ''
    result['data']['teams'] = list(reversed(result['data']['teams']))
    next(row for row in result['data']['teams'] if row['playerID'] == '17863')['nickname'] = ''
    raw = _write_source_raw(tmp_path, result, 66845)
    original = raw.read_bytes()
    index = build_source_name_index(tmp_path / 'raw')
    assert index['request_count'] == 0 and index['checked'] == 2 and index['accepted'] == 2
    recovered = index['names_by_source_id']['17863']
    assert recovered['name'] == 'Parukia' and recovered['references'][0]['raw_file'] == str(anchor.resolve())
    names = index['names_by_source_id']
    audit = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], names_by_source_id=names)
    assert audit['changed_records'] == 1 and audit['applied'] == 0 and db.session.query(Match).count() == 0
    proof = audit['records'][0]['recovered_player_names'][0]
    assert proof['source_player_id'] == '17863' and proof['references'][0]['raw_sha256']
    applied = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845],
                                     names_by_source_id=names, apply=True)
    assert applied['request_count'] == 0 and applied['applied'] == 1 and applied['blocked'] == 0
    assert db.session.query(Player).filter_by(team_name='EDG', position='e').one().name == 'Parukia'
    assert db.session.query(Player).count() == 10 and db.session.query(SyncTask).one().status == 'imported'
    assert raw.read_bytes() == original
    repeat = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], names_by_source_id=names)
    assert repeat['changed_records'] == 0


def test_source_name_index_refuses_conflicts_and_explicit_wrong_result_game_ids(identity_result, tmp_path):
    result = identity_result
    _write_source_raw(tmp_path, result, 66841)
    conflict = copy.deepcopy(result)
    conflict['data']['result_list']['blue_star_e_name'] = 'UnrelatedNickname'
    _write_source_raw(tmp_path, conflict, 66842)
    wrong = copy.deepcopy(result)
    wrong['data']['resultID'] = '999'
    _write_source_raw(tmp_path, wrong, 66843)
    nonlol = copy.deepcopy(result)
    nonlol['data']['gameID'] = '2'
    _write_source_raw(tmp_path, nonlol, 66844)
    index = build_source_name_index(tmp_path / 'raw')
    assert '17863' not in index['names_by_source_id']
    assert index['conflicts']['17863'] == ['Parukia', 'UnrelatedNickname']
    assert len(index['rejected']) == 2
    result['data']['result_list']['blue_star_e_name'] = ''
    normalized = normalize_result(result, 66845, allow_incomplete=True, names_by_source_id=index['names_by_source_id'])
    assert len(normalized['players']) == 9 and not normalized.get('recovered_player_names')


def test_source_name_index_casefold_is_only_for_conflict_check_not_alias_guessing(identity_result, tmp_path):
    result = identity_result
    _write_source_raw(tmp_path, result, 66841)
    variant = copy.deepcopy(result)
    variant['data']['result_list']['blue_star_e_name'] = 'PARUKIA'
    next(row for row in variant['data']['teams'] if row['playerID'] == '17863')['nickname'] = 'PARUKIA'
    _write_source_raw(tmp_path, variant, 66842)
    index = build_source_name_index(tmp_path / 'raw')
    assert '17863' not in index['conflicts'] and index['names_by_source_id']['17863']['name'] == 'Parukia'


@pytest.mark.parametrize('mismatch', ['duplicate_slot_id', 'wrong_color', 'duplicate_team_id'])
def test_name_recovery_refuses_ambiguous_current_identity_instead_of_array_position(identity_result, tmp_path, mismatch):
    result = identity_result
    _write_source_raw(tmp_path, result, 66844)
    names = build_source_name_index(tmp_path / 'raw')['names_by_source_id']
    result['data']['result_list']['blue_star_e_name'] = ''
    target = next(row for row in result['data']['teams'] if row['playerID'] == '17863')
    if mismatch == 'duplicate_slot_id':
        result['data']['result_list']['red_star_e_playerID'] = '17863'
    elif mismatch == 'wrong_color':
        target['color'] = 'red'
    else:
        result['data']['teams'].append(copy.deepcopy(target))
    normalized = normalize_result(result, 66845, allow_incomplete=True, names_by_source_id=names)
    assert len(normalized['players']) == 9 and not normalized.get('recovered_player_names')


def test_recovery_replay_blocks_changed_reference_and_keeps_original_target(db, identity_result, tmp_path):
    result = identity_result
    anchor = _write_source_raw(tmp_path, result, 66844)
    names = build_source_name_index(tmp_path / 'raw')['names_by_source_id']
    result['data']['result_list']['blue_star_e_name'] = ''
    raw = _write_source_raw(tmp_path, result, 66845)
    original = raw.read_bytes()
    anchor.write_text('{}', encoding='utf-8')
    audit = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845],
                                   names_by_source_id=names, apply=True)
    assert audit['blocked'] == 1 and audit['applied'] == 0 and db.session.query(Match).count() == 0
    assert 'SHA' in audit['records'][0]['error'] and raw.read_bytes() == original
