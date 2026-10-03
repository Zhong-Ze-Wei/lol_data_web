import copy
import json
from datetime import datetime

import pytest

from app.models.sync import HistorySeries, HistoryStage, HistoryTournament
from app.services.history import _discover_tournament
from app.services.spider import SourceHTTPError
from tests.test_history import HistoricalSource, run


class ParentScheduleSource(HistoricalSource):
    def __init__(self, result, *, child_status=404, parent_error=None, **kwargs):
        super().__init__(result, **kwargs)
        self.child_status = child_status
        self.parent_error = parent_error

    def get(self, url):
        response = super().get(url)
        response.text = response.text.replace('"week_player_select_list": []',
                                              '"week_player_select_list": [{"id": "765"}]')
        return response

    def get_json(self, url):
        self._call(url)
        if '/tr/' in url:
            return [{'roundID': '765', 'name': '常规赛', 'is_now_week': 0,
                     'round_son': [{'id': '2465', 'name': '第一周'}, {'id': '2466', 'name': '第二周'}]}]
        if not url.endswith('/p_765.json'):
            raise SourceHTTPError(url, self.child_status)
        if self.parent_error == 'http':
            raise SourceHTTPError(url, 404)
        if self.parent_error == 'shape':
            return {'error': 'not a schedule list'}
        rows = [{'matchID': '20674', 'match_date': '2011-06-18', 'match_time': '16:30',
                 'status': '2', 'is_publist': 0, 'team_a_win': '1', 'team_b_win': '0'},
                {'matchID': '20675', 'match_date': '2011-06-19', 'match_time': '16:30',
                 'status': '2', 'is_publist': 0, 'team_a_win': '0', 'team_b_win': '1'}]
        if self.parent_error == 'duplicate':
            rows.append(copy.deepcopy(rows[0]))
        return rows


@pytest.fixture
def result():
    # These tests discover schedules only; no result-detail request is allowed.
    return {}


def test_missing_week_caches_discover_parent_once_without_claiming_weeks_resolved(db, result, tmp_path):
    source = ParentScheduleSource(result)
    report, code = run(source, tmp_path)
    assert code == 2
    parent = db.session.query(HistoryStage).filter_by(cache_key='p_765').one()
    assert parent.status == 'discovered' and parent.series_count == 2
    assert db.session.query(HistoryTournament).one().stage_count == 3
    assert [item.series_id for item in db.session.query(HistorySeries).order_by(HistorySeries.series_id)] == [20674, 20675]
    assert all(item.stage_id == parent.id for item in db.session.query(HistorySeries))
    assert source.calls.count('https://img.scoregg.com/tr_round/p_765.json') == 1
    children = db.session.query(HistoryStage).filter(HistoryStage.cache_key != 'p_765').all()
    assert all(item.status == 'failed' and item.failure_count == 1 and 'HTTP 404' in item.last_error for item in children)
    coverage = report['details']['coverage']
    assert coverage['failed_tasks'] == 2 and coverage['snapshot_completed'] is False
    assert coverage['complete_available'] is False and coverage['counts']['series']['pending'] == 2
    assert json.loads((tmp_path / 'raw/history/stages/333/p_765.json').read_text(encoding='utf-8'))[0]['matchID'] == '20674'


def test_parent_cursor_survives_child_failure_and_budget_exit(db, result, tmp_path):
    source = ParentScheduleSource(result, budget=3)
    report, code = run(source, tmp_path)
    assert code == 4 and report['status'] == 'budget_exhausted'
    parent = db.session.query(HistoryStage).filter_by(cache_key='p_765').one()
    assert parent.status == 'queued' and parent.attempts == 0
    resumed = ParentScheduleSource(result, budget=2)
    report, code = run(resumed, tmp_path)
    assert code == 2
    assert parent.status == 'discovered' and parent.series_count == 2
    assert resumed.calls == ['https://img.scoregg.com/tr_round/2466.json',
                             'https://img.scoregg.com/tr_round/p_765.json']


@pytest.mark.parametrize('parent_error', ['http', 'shape', 'duplicate'])
def test_invalid_parent_keeps_failure_and_no_partial_series(db, result, tmp_path, parent_error):
    report, code = run(ParentScheduleSource(result, parent_error=parent_error), tmp_path)
    assert code == 2
    parent = db.session.query(HistoryStage).filter_by(cache_key='p_765').one()
    assert parent.status == 'failed' and parent.failure_count == 1
    assert db.session.query(HistorySeries).count() == 0
    assert report['details']['coverage']['failed_tasks'] == 3
    assert db.session.query(HistoryStage).count() == 3


def test_transient_child_http_error_does_not_change_discovery_path(db, result, tmp_path):
    report, code = run(ParentScheduleSource(result, child_status=500), tmp_path)
    assert code == 2 and report['details']['coverage']['failed_tasks'] == 2
    assert db.session.query(HistoryStage).filter_by(cache_key='p_765').count() == 0


def test_parent_already_discovered_is_not_reset_by_another_missing_week(db, result, tmp_path):
    source = ParentScheduleSource(result)
    run(source, tmp_path)
    parent = db.session.query(HistoryStage).filter_by(cache_key='p_765').one()
    child = db.session.query(HistoryStage).filter_by(cache_key='2465').one()
    previous = parent.raw_sha256, parent.attempts, parent.discovered_at
    child.status, child.next_retry_at = 'queued', None
    db.session.commit()
    repeat = ParentScheduleSource(result)
    run(repeat, tmp_path)
    assert parent.status == 'discovered'
    assert (parent.raw_sha256, parent.attempts, parent.discovered_at) == previous
    assert repeat.calls == ['https://img.scoregg.com/tr_round/2465.json']
    assert db.session.query(HistoryStage).count() == 3 and db.session.query(HistorySeries).count() == 2


def test_parent_cannot_reassign_series_from_another_tournament(db, result, tmp_path):
    run(ParentScheduleSource(result, budget=2), tmp_path)
    db.session.add(HistoryTournament(tournament_id=777, name='Other', status='discovered'))
    db.session.flush()
    other = HistoryStage(tournament_id=777, cache_key='p_1', parent_round_id=1, status='discovered')
    db.session.add(other)
    db.session.flush()
    db.session.add(HistorySeries(series_id=20674, tournament_id=777, stage_id=other.id,
                                scheduled_at=datetime(2011, 6, 18), status='discovered'))
    db.session.commit()
    report, code = run(ParentScheduleSource(result), tmp_path)
    assert code == 2
    assert db.session.get(HistorySeries, 20674).tournament_id == 777
    parent = db.session.query(HistoryStage).filter_by(tournament_id=333, cache_key='p_765').one()
    assert parent.status == 'failed' and '两个赛事' in parent.last_error
    assert db.session.query(HistorySeries).count() == 1
    assert report['details']['coverage']['failed_tasks'] == 3


def test_catalog_stage_refresh_keeps_existing_parent_cursor_and_inventory_count(db, result, tmp_path):
    run(ParentScheduleSource(result), tmp_path)
    parent = db.session.query(HistoryStage).filter_by(cache_key='p_765').one()
    tour = db.session.get(HistoryTournament, 333)
    previous = parent.raw_sha256, parent.attempts, parent.discovered_at
    _discover_tournament(ParentScheduleSource(result), tour, tmp_path / 'raw', datetime(2026, 10, 4))
    assert tour.stage_count == 3
    assert parent.status == 'discovered'
    assert (parent.raw_sha256, parent.attempts, parent.discovered_at) == previous
