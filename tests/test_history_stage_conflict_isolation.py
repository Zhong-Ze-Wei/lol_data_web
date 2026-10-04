"""阶段中一个跨赛事 BO 不能吞掉其他合法 BO；夹具不访问真实来源。"""

import copy
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.models.match import Match
from app.models.sync import HistorySeries, HistoryStage, HistoryTournament, SyncTask
from app.services import history
from app.services.spider import RequestBudget
from scripts.history_worker import next_action
from scripts.pipeline import run_pipeline


OWN_IDS = [sid for sid in range(15473, 15483) if sid != 15481]


def row(sid, *, pub=1, year=2022):
    return {'matchID': str(sid), 'match_date': f'{year}-01-15', 'match_time': '17:00',
            'status': '2', 'is_publist': pub, 'team_a_win': '1', 'team_b_win': '0',
            'teamID_a': '1', 'teamID_b': '17', 'team_short_name_a': 'EDG', 'team_short_name_b': 'LGD'}


def snapshot(entity):
    return {column.name: copy.deepcopy(getattr(entity, column.name)) for column in entity.__table__.columns}


@pytest.fixture
def clock(monkeypatch):
    instant = [datetime(2026, 10, 4, 0)]
    monkeypatch.setattr(history, 'utc_now', lambda: instant[0])
    return instant


@pytest.fixture
def seeded(db, tmp_path, clock):
    db.session.add_all([
        HistoryTournament(tournament_id=244, name='Fixture LCK', start_date=date(2022, 1, 1),
                          end_date=date(2022, 12, 31), status='discovered', last_seen_at=clock[0]),
        HistoryTournament(tournament_id=403, name='Fixture LCL', start_date=date(2017, 1, 1),
                          end_date=date(2017, 12, 31), status='discovered', last_seen_at=clock[0])])
    db.session.flush()
    stage = HistoryStage(tournament_id=244, cache_key='2023', parent_round_id=2000,
                         status='queued', source_json='{}')
    foreign_stage = HistoryStage(tournament_id=403, cache_key='old', parent_round_id=4000,
                                 status='discovered', source_json='{}')
    db.session.add_all([stage, foreign_stage]); db.session.flush()
    foreign_file = tmp_path / 'old-foreign-stage.json'
    foreign_file.write_text(json.dumps([row(15481, year=2017)]), encoding='utf-8')
    foreign = HistorySeries(series_id=15481, tournament_id=403, stage_id=foreign_stage.id,
                            scheduled_at=datetime(2017, 1, 15, 17), source_status='2', is_publist=1,
                            team_a_score=1, team_b_score=0, source_json=json.dumps(row(15481, year=2017)),
                            schedule_raw_file=str(foreign_file),
                            schedule_raw_sha256=hashlib.sha256(foreign_file.read_bytes()).hexdigest(),
                            status='discovered', result_ids='[]', attempts=3, failure_count=2,
                            last_error='Prior diagnostic, must be preserved')
    match = Match(match_id=66890, series_id=15481, tournament_id=403, tournament_name='Fixture LCL',
                  date=datetime(2017, 1, 15, 17), date_source='schedule', source='scoregg', verified=True,
                  game_time=1200, red_team_name='Original Red', blue_team_name='Original Blue',
                  team_name_provenance={'fixture': 'previous immutable evidence'})
    task = SyncTask(task_key='result:66890', result_id=66890, series_id=15481, tournament_id=403,
                    scheduled_at=datetime(2017, 1, 15, 17), status='imported', attempts=2, failure_count=0)
    db.session.add_all([foreign, match, task]); db.session.commit()
    return stage, foreign, match, task


class LocalStageSource:
    def __init__(self, rows, budget=50):
        self.rows = rows
        self.calls = []
        self.budget = RequestBudget(budget, 60)

    def get(self, url):
        raise AssertionError(f'目录无需重复读取: {url}')

    def get_json(self, url):
        assert url == 'https://img.scoregg.com/tr_round/2023.json'
        self.budget.reserve(); self.calls.append('stage')
        return copy.deepcopy(self.rows)

    def get_result_list(self, series_id):
        assert series_id in OWN_IDS
        self.budget.reserve(); self.calls.append(('resultlist', series_id))
        return {'code': 200, 'data': [{'resultID': str(70000 + series_id)}]}

    def get_result(self, result_id):
        sid = result_id - 70000
        assert sid in OWN_IDS
        self.budget.reserve(); self.calls.append(('result', result_id))
        payload = json.loads((Path(__file__).parent / 'fixtures/scoregg_result_66845.json').read_bytes())
        payload['data']['resultID'] = str(result_id)
        for block in ['max_mvp', 'max_beiguo']:
            payload['data'][block]['match_id'] = str(sid)
        payload['data']['result_list'].update(red_teamID='17', blue_teamID='1', win_teamID='17')
        return payload


def run(source, tmp_path, clock, *, phase='all', max_attempts=5):
    return run_pipeline('history', client=source, raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports',
                        now=clock[0], phase=phase, max_attempts=max_attempts)


def all_rows(pub=1):
    return [row(sid, pub=pub) for sid in range(15473, 15483)]


def assert_preserved(entities, before):
    assert [snapshot(entity) for entity in entities] == before


def test_one_foreign_bo_is_isolated_and_nine_legal_bos_are_imported(db, seeded, tmp_path, clock):
    stage, *foreign_entities = seeded
    before = [snapshot(entity) for entity in foreign_entities]
    source = LocalStageSource(all_rows())
    report, code = run(source, tmp_path, clock)
    assert code == 2 and report['status'] == 'partial' and report['imported'] == 9
    assert stage.status == 'failed' and stage.failure_count == 1 and stage.attempts == 1
    assert stage.next_retry_at == clock[0] + timedelta(minutes=2)
    assert stage.discovered_at is None and stage.series_count == 10
    failure = next(outcome for outcome in report['details']['outcomes'] if outcome.get('entity') == 'stage')
    assert failure['conflicting_series_ids'] == [15481] and failure['persisted_series_count'] == 9
    assert '15481' in stage.last_error and '9' in stage.last_error
    archive = failure['source_archive']; encoded = Path(archive['raw_file']).read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == archive['sha256'] and json.loads(encoded) == all_rows()
    own = db.session.query(HistorySeries).filter_by(tournament_id=244).all()
    assert sorted(series.series_id for series in own) == OWN_IDS
    assert all(series.stage_id == stage.id and series.status == 'discovered' for series in own)
    assert all(series.schedule()['source_archive'] == archive for series in own)
    assert all(match.team_name_provenance['schedule']['archive'] == archive
               for match in db.session.query(Match).filter_by(tournament_id=244).all())
    assert len(source.calls) == 19 and source.calls.count('stage') == 1
    assert_preserved(foreign_entities, before)
    coverage = report['details']['coverage']
    assert coverage['failed_tasks'] == 1 and not coverage['has_runnable_work']
    assert not any(coverage[key] for key in ['discovery_complete', 'snapshot_completed', 'complete_available'])


@pytest.mark.parametrize('max_attempts', [3, 5, 7])
def test_budget_exit_keeps_nine_and_next_batch_works_under_exhausted_stage(db, seeded, tmp_path, clock, max_attempts):
    stage, *foreign_entities = seeded
    before = [snapshot(entity) for entity in foreign_entities]
    stage.failure_count = max_attempts - 1; db.session.commit()
    first = LocalStageSource(all_rows(), budget=2)
    report, code = run(first, tmp_path, clock, max_attempts=max_attempts)
    assert code == 4 and report['status'] == 'budget_exhausted'
    assert stage.status == 'failed' and stage.failure_count == max_attempts
    assert db.session.query(HistorySeries).filter_by(tournament_id=244).count() == 9
    assert report['details']['coverage']['has_runnable_work']
    failed_stage = snapshot(stage)
    second = LocalStageSource(all_rows())
    report, code = run(second, tmp_path, clock, max_attempts=max_attempts)
    assert code == 2 and report['status'] == 'waiting_retry' and report['imported'] == 9
    assert 'stage' not in second.calls and snapshot(stage) == failed_stage
    coverage = report['details']['coverage']
    assert coverage['ready_tasks'] == 0 and coverage['failed_tasks'] == coverage['exhausted_tasks'] == 1
    assert coverage['next_retry_at'] is None and next_action(code, coverage) == 'failed'
    third = LocalStageSource(all_rows())
    report, code = run(third, tmp_path, clock, max_attempts=max_attempts)
    assert third.calls == [] and report['status'] == 'waiting_retry' and snapshot(stage) == failed_stage
    assert_preserved(foreign_entities, before)


def test_all_conflicts_keep_failure_without_fake_runnable_work(db, seeded, tmp_path, clock):
    stage, *foreign_entities = seeded
    before = [snapshot(entity) for entity in foreign_entities]
    stage.failure_count = 4; db.session.commit()
    report, code = run(LocalStageSource([row(15481)]), tmp_path, clock)
    assert code == 2 and stage.failure_count == 5 and stage.status == 'failed'
    outcome = report['details']['outcomes'][0]
    assert outcome['persisted_series_count'] == 0 and outcome['conflicting_series_ids'] == [15481]
    assert db.session.query(HistorySeries).filter_by(tournament_id=244).count() == 0
    assert not report['details']['coverage']['has_runnable_work']
    assert next_action(code, report['details']['coverage']) == 'failed'
    assert_preserved(foreign_entities, before)


@pytest.mark.parametrize('bad', ['structure', 'row_type', 'date', 'duplicate', 'score'])
def test_other_validation_errors_still_fail_whole_stage_without_legal_prefix(db, seeded, tmp_path, clock, bad):
    stage, *foreign_entities = seeded
    before = [snapshot(entity) for entity in foreign_entities]
    rows = all_rows()
    if bad == 'structure': rows = {'data': rows}
    elif bad == 'row_type': rows.append('not a row')
    elif bad == 'date': rows[-1]['match_date'] = 'bad-date'
    elif bad == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    else: rows[-1]['team_a_win'] = 'bad-score'
    source = LocalStageSource(rows)
    report, code = run(source, tmp_path, clock)
    assert code == 2 and stage.status == 'failed' and stage.failure_count == 1
    assert db.session.query(HistorySeries).filter_by(tournament_id=244).count() == 0
    assert source.calls == ['stage'] and report['imported'] == 0
    assert_preserved(foreign_entities, before)


def test_discover_phase_persists_nine_without_fetching_details_and_retry_is_idempotent(db, seeded, tmp_path, clock):
    stage, *foreign_entities = seeded
    before = [snapshot(entity) for entity in foreign_entities]
    report, code = run(LocalStageSource(all_rows()), tmp_path, clock, phase='discover')
    assert code == 2 and stage.status == 'failed' and stage.failure_count == 1
    assert db.session.query(HistorySeries).filter_by(tournament_id=244).count() == 9
    assert db.session.query(SyncTask).filter_by(tournament_id=244).count() == 9
    assert db.session.query(Match).filter_by(tournament_id=244).count() == 0
    prior_bytes = [p.read_bytes() for p in (tmp_path / 'raw/history/stages/244/failed-attempts').glob('*.json')]
    clock[0] += timedelta(minutes=3)
    repeated = LocalStageSource(all_rows())
    report, code = run(repeated, tmp_path, clock, phase='discover')
    assert code == 2 and stage.failure_count == 2 and stage.status == 'failed'
    assert repeated.calls == ['stage']
    assert db.session.query(HistorySeries).filter_by(tournament_id=244).count() == 9
    assert db.session.query(SyncTask).filter_by(tournament_id=244).count() == 9
    assert all(old in [p.read_bytes() for p in (tmp_path / 'raw/history/stages/244/failed-attempts').glob('*.json')]
               for old in prior_bytes)
    assert_preserved(foreign_entities, before)


def test_real_source_removing_conflict_recovers_without_overwriting_old_archives(db, seeded, tmp_path, clock):
    stage, *foreign_entities = seeded
    before = [snapshot(entity) for entity in foreign_entities]
    first, _ = run(LocalStageSource(all_rows(pub=0)), tmp_path, clock)
    assert stage.status == 'failed' and stage.failure_count == 1
    archive = first['details']['outcomes'][0]['source_archive']
    old_paths = [Path(archive['raw_file']), tmp_path / 'raw/history/stages/244/2023.json']
    old_bytes = [path.read_bytes() for path in old_paths]
    clock[0] += timedelta(minutes=3)
    recovered = LocalStageSource([row(sid) for sid in OWN_IDS])
    report, code = run(recovered, tmp_path, clock)
    assert code == 0 and report['imported'] == 9
    assert stage.status == 'discovered' and stage.failure_count == 0 and stage.last_error is None
    assert stage.next_retry_at is None and stage.series_count == 9
    assert [path.read_bytes() for path in old_paths] == old_bytes
    assert_preserved(foreign_entities, before)


def test_partial_refresh_preserves_old_stage_and_legacy_row_binding_through_recovery(db, seeded, tmp_path, clock):
    stage, *_ = seeded
    legacy_row = row(15472)
    old_file = tmp_path / 'old-successful-stage.json'
    old_file.write_text(json.dumps([legacy_row]), encoding='utf-8')
    old_bytes = old_file.read_bytes(); old_sha = hashlib.sha256(old_bytes).hexdigest()
    stage.raw_file, stage.raw_sha256 = str(old_file), old_sha
    legacy = HistorySeries(series_id=15472, tournament_id=244, stage_id=stage.id,
                           scheduled_at=datetime(2022, 1, 15, 17), source_status='2', is_publist=1,
                           status='discovered', source_json=json.dumps(legacy_row))
    db.session.add(legacy); db.session.commit()
    report, code = run(LocalStageSource(all_rows(pub=0)), tmp_path, clock)
    assert code == 2 and stage.status == 'failed'
    assert (stage.raw_file, stage.raw_sha256) == (str(old_file), old_sha)
    assert legacy.schedule()['source_archive'] == {'raw_file': str(old_file), 'sha256': old_sha}
    clock[0] += timedelta(minutes=3)
    report, code = run(LocalStageSource([row(sid, pub=0) for sid in OWN_IDS]), tmp_path, clock)
    assert code == 0 and stage.status == 'discovered'
    assert stage.raw_file != str(old_file)
    assert (legacy.schedule_raw_file, legacy.schedule_raw_sha256) == (str(old_file), old_sha)
    assert old_file.read_bytes() == old_bytes
    assert legacy.schedule()['source_row'] == legacy_row


def test_repeated_conflicting_response_does_not_overwrite_first_failed_alias(db, seeded, tmp_path, clock):
    first, _ = run(LocalStageSource(all_rows(pub=0)), tmp_path, clock)
    ordinary = tmp_path / 'raw/history/stages/244/2023.json'
    first_archive = Path(first['details']['outcomes'][0]['source_archive']['raw_file'])
    old = {p: p.read_bytes() for p in [ordinary, first_archive]}
    clock[0] += timedelta(minutes=3)
    changed = all_rows(pub=0)
    changed[0]['team_a_win'] = '3'
    second, _ = run(LocalStageSource(changed), tmp_path, clock)
    second_archive = second['details']['outcomes'][0]['source_archive']
    assert json.loads(Path(second_archive['raw_file']).read_bytes()) == changed
    assert all(path.read_bytes() == encoded for path, encoded in old.items())
    assert second_archive['raw_file'] != str(first_archive)


def test_archive_error_does_not_commit_any_legal_bo(db, seeded, tmp_path, clock, monkeypatch):
    stage, *foreign_entities = seeded
    before = [snapshot(entity) for entity in foreign_entities]
    original = history._archive
    def broken(path, payload):
        if 'failed-attempts' in Path(path).parts:
            raise OSError('simulated failed-stage archive failure')
        return original(path, payload)
    monkeypatch.setattr(history, '_archive', broken)
    source = LocalStageSource(all_rows())
    report, code = run(source, tmp_path, clock)
    assert code == 2 and stage.status == 'failed' and stage.failure_count == 1
    assert 'simulated failed-stage archive failure' in stage.last_error
    assert source.calls == ['stage'] and db.session.query(HistorySeries).filter_by(tournament_id=244).count() == 0
    assert_preserved(foreign_entities, before)
