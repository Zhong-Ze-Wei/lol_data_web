"""待发布系列必须经可重试的阶段刷新；耗尽和退避不能驱动空批次。"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.models.sync import HistorySeries, HistoryStage, HistoryTournament, SyncTask
from app.services import history
from app.services.spider import RequestBudget, SourceHTTPError
from scripts.history_worker import next_action
from scripts.pipeline import run_pipeline


@pytest.fixture
def clock(monkeypatch):
    instant = datetime(2026, 10, 4, 0)
    monkeypatch.setattr(history, 'utc_now', lambda: instant)
    return instant


def schedule(series_id=20674, published=0):
    return {'matchID': str(series_id), 'match_date': '2011-06-18', 'match_time': '16:30',
            'status': '2', 'is_publist': published, 'team_a_win': '1', 'team_b_win': '0'}


def seed(db, clock, *, failures=5, stage_status='failed', stage_retry=None, series_retry=None):
    db.session.add(HistoryTournament(tournament_id=333, name='Previously scanned',
                                     start_date=date(2011, 1, 1), end_date=date(2011, 12, 31),
                                     status='discovered', last_seen_at=clock))
    db.session.flush()
    stage = HistoryStage(tournament_id=333, cache_key='p_765', parent_round_id=765,
                         status=stage_status, failure_count=failures,
                         last_error='HTTP 404: archived stage', next_retry_at=stage_retry,
                         source_json=json.dumps({'is_now_week': 1}))
    db.session.add(stage)
    db.session.flush()
    series = HistorySeries(series_id=20674, tournament_id=333, stage_id=stage.id,
                           scheduled_at=datetime(2011, 6, 18, 16, 30), source_status='2',
                           is_publist=0, status='pending', next_retry_at=series_retry,
                           source_json=json.dumps(schedule()))
    db.session.add(series)
    db.session.commit()
    return stage, series


def stage_snapshot(stage):
    return {column.name: getattr(stage, column.name) for column in HistoryStage.__table__.columns}


class LocalSource:
    """仅本地夹具响应；意料之外的请求立即失败，不访问网络。"""
    def __init__(self, *, published=0, stage_404=False):
        self.budget = RequestBudget(20, 60)
        self.calls = []
        self.published = published
        self.stage_404 = stage_404

    def get(self, url):
        raise AssertionError(f'无需重新读取目录: {url}')

    def get_json(self, url):
        assert url.endswith('/tr_round/p_765.json')
        self.budget.reserve()
        self.calls.append('stage')
        if self.stage_404:
            raise SourceHTTPError(url, 404)
        return [schedule(published=self.published)]

    def get_result_list(self, series_id):
        assert series_id == 20674
        self.budget.reserve()
        self.calls.append('resultlist')
        return {'code': 200, 'data': [{'resultID': '66845'}]}

    def get_result(self, result_id):
        assert result_id == 66845
        self.budget.reserve()
        self.calls.append('result')
        payload = json.loads((Path(__file__).parent / 'fixtures/scoregg_result_66845.json').read_text('utf-8'))
        # 与阶段真实BO夹具同步，其他战报指标沿用原fixture。
        payload['data']['max_mvp']['match_id'] = '20674'
        payload['data']['max_beiguo']['match_id'] = '20674'
        return payload


def run(source, tmp_path, clock, max_attempts=5):
    return run_pipeline('history', client=source, raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports',
                        now=clock, max_attempts=max_attempts)


def test_stage_404_reaches_budget_then_following_real_batches_keep_failure_and_stop(db, clock, tmp_path):
    stage, _ = seed(db, clock, failures=4, stage_retry=clock - timedelta(seconds=1),
                    series_retry=clock - timedelta(seconds=1))
    first = LocalSource(stage_404=True)
    report, code = run(first, tmp_path, clock)
    assert first.calls == ['stage'] and stage.status == 'failed' and stage.failure_count == 5
    coverage = report['details']['coverage']
    assert code == 2 and report['status'] == 'partial'
    assert coverage['has_runnable_work'] is False and coverage['ready_tasks'] == 0
    assert coverage['failed_tasks'] == coverage['exhausted_tasks'] == 1
    assert next_action(code, coverage) == 'failed'
    failed = stage_snapshot(stage)
    for _ in range(2):
        source = LocalSource()
        report, code = run(source, tmp_path, clock)
        coverage = report['details']['coverage']
        assert source.calls == [] and report['request_count'] == 0
        assert report['status'] == 'waiting_retry' and code == 2
        assert stage_snapshot(stage) == failed
        assert coverage['failed_tasks'] == coverage['exhausted_tasks'] == 1
        assert coverage['ready_tasks'] == 0 and coverage['next_retry_at'] is None
        assert not any(coverage[key] for key in ('discovery_complete', 'snapshot_completed', 'complete_available'))
        assert next_action(code, coverage) == 'failed'


def test_nineteen_exhausted_stages_are_preserved_and_not_hidden_by_due_pending(db, clock, tmp_path):
    seed(db, clock, series_retry=clock - timedelta(seconds=1))
    db.session.add_all(HistoryStage(tournament_id=333, cache_key=str(index), parent_round_id=765,
                                   status='failed', failure_count=5, last_error='HTTP 404',
                                   next_retry_at=clock - timedelta(seconds=1)) for index in range(18))
    db.session.commit()
    before = [stage_snapshot(stage) for stage in db.session.query(HistoryStage).order_by(HistoryStage.id)]
    source = LocalSource()
    report, code = run(source, tmp_path, clock)
    coverage = report['details']['coverage']
    assert source.calls == [] and code == 2
    assert coverage['failed_tasks'] == coverage['exhausted_tasks'] == 19
    assert coverage['has_runnable_work'] is False and coverage['next_retry_at'] is None
    assert [stage_snapshot(stage) for stage in db.session.query(HistoryStage).order_by(HistoryStage.id)] == before
    assert next_action(code, coverage) == 'failed'


@pytest.mark.parametrize('series_delay', [-1, 600])
def test_pending_series_cannot_bypass_failed_parent_backoff_or_wake_worker_early(db, clock, tmp_path, series_delay):
    retry = clock + timedelta(hours=2)
    stage, _ = seed(db, clock, failures=2, stage_retry=retry,
                    series_retry=clock + timedelta(seconds=series_delay))
    before = stage_snapshot(stage)
    coverage = history.coverage_report()
    assert coverage['has_runnable_work'] is False
    assert coverage['next_retry_at'] == retry.isoformat() + 'Z'
    source = LocalSource()
    report, code = run(source, tmp_path, clock)
    assert source.calls == [] and code == 2
    assert stage_snapshot(stage) == before
    assert report['details']['coverage']['failed_tasks'] == 1
    assert next_action(code, report['details']['coverage']) == 'retry_later'


def test_future_pending_under_exhausted_parent_has_no_actionable_retry_deadline(db, clock, tmp_path):
    stage, _ = seed(db, clock, stage_retry=clock + timedelta(minutes=10),
                    series_retry=clock + timedelta(minutes=20))
    before = stage_snapshot(stage)
    coverage = history.coverage_report()
    assert coverage['has_runnable_work'] is False and coverage['next_retry_at'] is None
    report, code = run(LocalSource(), tmp_path, clock)
    assert stage_snapshot(stage) == before
    assert next_action(code, report['details']['coverage']) == 'failed'


def test_due_failed_parent_below_budget_can_refresh_publish_and_import(db, clock, tmp_path):
    stage, series = seed(db, clock, failures=2, stage_retry=clock - timedelta(seconds=1),
                         series_retry=clock - timedelta(seconds=1))
    assert history.coverage_report()['has_runnable_work'] is True
    source = LocalSource(published=1)
    report, code = run(source, tmp_path, clock)
    assert source.calls == ['stage', 'resultlist', 'result'] and code == 0
    assert stage.status == series.status == 'discovered' and stage.failure_count == 0
    assert stage.last_error is None and stage.next_retry_at is None
    coverage = report['details']['coverage']
    assert coverage['counts']['results']['verified'] == coverage['counts']['results']['complete'] == 1
    assert coverage['complete_available'] is True and next_action(code, coverage) == 'completed'
    repeat = LocalSource(published=1)
    assert run(repeat, tmp_path, clock)[1] == 0 and repeat.calls == []


@pytest.mark.parametrize('stage_status', ['discovered', 'queued', 'pending'])
def test_eligible_parent_keeps_existing_unpublished_refresh_behavior(db, clock, tmp_path, stage_status):
    stage, series = seed(db, clock, failures=0, stage_status=stage_status,
                         stage_retry=clock + timedelta(days=1) if stage_status == 'pending' else None,
                         series_retry=clock - timedelta(seconds=1))
    assert history.coverage_report()['ready_tasks'] == 1  # 一次阶段刷新，不重复计系列游标。
    source = LocalSource()
    report, code = run(source, tmp_path, clock)
    assert source.calls == ['stage'] and code == 0
    assert stage.status == 'discovered' and series.status == 'pending'
    coverage = report['details']['coverage']
    assert coverage['snapshot_completed'] is True and coverage['complete_available'] is False
    assert coverage['pending_publication'] == 1 and coverage['has_runnable_work'] is False
    assert next_action(code, coverage) == 'completed'  # 本轮快照退出，未宣称全部可用战报完成。


def test_multiple_due_series_share_one_actual_stage_refresh(db, clock, tmp_path):
    stage, _ = seed(db, clock, failures=0, stage_status='queued',
                    series_retry=clock - timedelta(seconds=1))
    db.session.add(HistorySeries(series_id=20675, tournament_id=333, stage_id=stage.id,
                                 status='pending', source_status='2', is_publist=0,
                                 source_json=json.dumps(schedule(20675)),
                                 next_retry_at=clock - timedelta(seconds=1)))
    db.session.commit()
    assert history.coverage_report()['ready_tasks'] == 1

    class TwoSeriesSource(LocalSource):
        def get_json(self, url):
            return super().get_json(url) + [schedule(20675)]

    source = TwoSeriesSource()
    report, code = run(source, tmp_path, clock)
    assert source.calls == ['stage'] and code == 0
    assert report['details']['coverage']['pending_publication'] == 2
    assert report['details']['coverage']['has_runnable_work'] is False


def test_failed_series_keeps_own_future_retry_when_parent_stage_is_exhausted(db, clock, tmp_path):
    _, series = seed(db, clock)
    retry = clock + timedelta(hours=2)
    series.status, series.next_retry_at = 'failed', retry
    db.session.commit()
    source = LocalSource()
    report, code = run(source, tmp_path, clock)
    coverage = report['details']['coverage']
    assert source.calls == [] and coverage['has_runnable_work'] is False
    assert coverage['next_retry_at'] == retry.isoformat() + 'Z'
    assert next_action(code, coverage) == 'retry_later'


@pytest.mark.parametrize('series_status', ['queued', 'failed'])
def test_known_series_results_can_run_independently_of_exhausted_stage(db, clock, tmp_path, series_status):
    stage, series = seed(db, clock)
    series.status, series.is_publist = series_status, 1
    series.source_json = json.dumps(schedule(published=1))
    series.next_retry_at = clock - timedelta(seconds=1)
    db.session.commit()
    before = stage_snapshot(stage)
    assert history.coverage_report()['has_runnable_work'] is True
    source = LocalSource(published=1)
    report, code = run(source, tmp_path, clock)
    assert source.calls == ['resultlist', 'result']
    assert stage_snapshot(stage) == before
    assert report['details']['coverage']['counts']['results']['verified'] == 1
    assert report['details']['coverage']['failed_tasks'] == 1 and code == 2


@pytest.mark.parametrize('task_status', ['queued', 'failed', 'pending'])
def test_known_single_game_can_run_independently_of_exhausted_stage(db, clock, tmp_path, task_status):
    stage, _ = seed(db, clock, series_retry=clock - timedelta(seconds=1))
    db.session.add(SyncTask(task_key='result:66845', result_id=66845, series_id=20674,
                            tournament_id=333, status=task_status, failure_count=1,
                            next_retry_at=clock - timedelta(seconds=1)))
    db.session.commit()
    before = stage_snapshot(stage)
    assert history.coverage_report()['has_runnable_work'] is True
    source = LocalSource()
    report, code = run(source, tmp_path, clock)
    assert source.calls == ['result'] and stage_snapshot(stage) == before
    assert report['details']['coverage']['counts']['results']['verified'] == 1
    assert report['details']['coverage']['failed_tasks'] == 1 and code == 2


@pytest.mark.parametrize('max_attempts,failures,expected_calls', [(3, 3, []), (10, 5, ['stage'])])
def test_pending_refresh_uses_same_configured_retry_budget_as_scheduler(db, clock, tmp_path, max_attempts, failures, expected_calls):
    stage, _ = seed(db, clock, failures=failures, stage_retry=clock - timedelta(seconds=1),
                    series_retry=clock - timedelta(seconds=1))
    source = LocalSource()
    report, _ = run(source, tmp_path, clock, max_attempts=max_attempts)
    assert source.calls == expected_calls
    assert stage.failure_count == (failures if not expected_calls else 0)
    assert report['details']['coverage']['has_runnable_work'] is False
