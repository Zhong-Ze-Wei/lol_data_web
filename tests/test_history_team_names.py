"""赛程队名来源绑定、零 HTTP 重排和双原件冻结；名称为明确人工业务样例。"""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import HistoryTournament, HistoryStage, HistorySeries, SyncTask
from app.services import history
from app.services.ingestion import ingest_result
from app.services.spider import SourceError, discover_series, history_schedule


def _schedule_row():
    return {'matchID': '58146', 'match_date': '2016-01-31', 'match_time': '17:00',
            'status': '2', 'is_publist': '1', 'team_a_win': '0', 'team_b_win': '1',
            'teamID_a': '1', 'teamID_b': '17',
            'team_short_name_a': '历史EDG', 'team_short_name_b': '历史LGD',
            'other_source_field': {'kept': True}}


class ScheduleSource:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_json(self, url):
        self.calls.append(url)
        if '/tr/' in url:
            return [{'roundID': '11', 'round_son': []}]
        return copy.deepcopy(self.rows)

    def get(self, url):
        self.calls.append(url)
        page = {'gameID': '1', 'tournament_list': [
            {'tournamentID': '1007', 'name': 'LPL', 'start_date': '2016-01-01', 'end_date': '2016-02-10'}]}
        return SimpleNamespace(text='var t_data = ' + json.dumps(page) + ';')

    def get_result(self, result_id):
        raise AssertionError('名称重排必须复用本地详情，不请求上游')


def _prepared_result(db, tmp_path, *, partial=False):
    payload = json.loads((Path(__file__).parent / 'fixtures' / 'scoregg_result_66845.json').read_text(encoding='utf-8'))
    payload['data']['resultID'] = '66845'
    payload['data']['result_list'].update(red_teamID='17', blue_teamID='1')
    if partial:
        payload['data']['result_list'].update(game_time_m='0', game_time_s='1', blue_star_e_name='')
    row = _schedule_row()
    db.session.add(HistoryTournament(tournament_id=1007, name='人工LPL样例'))
    db.session.flush()
    stage = HistoryStage(tournament_id=1007, cache_key='p_11', parent_round_id=11, status='discovered')
    stage.raw_file, stage.raw_sha256 = history._archive(tmp_path / 'raw' / 'history' / 'stages' / '1007' / 'p_11.json', [row])
    db.session.add(stage)
    db.session.flush()
    series = HistorySeries(series_id=58146, tournament_id=1007, stage_id=stage.id,
                           scheduled_at=datetime(2016, 1, 31, 17), source_status='2', is_publist=1,
                           source_json=json.dumps(row), result_ids='[66845]', status='discovered')
    db.session.add(series)
    db.session.commit()
    raw_file, sha256 = history._archive(tmp_path / 'raw' / 'scoregg' / '66845.json', payload)
    previous_schedule = series.schedule()
    previous_schedule.pop('source_row')
    previous_schedule.pop('source_archive')
    previous_schedule['detail_archive'] = {'raw_file': raw_file, 'sha256': sha256}
    assert ingest_result(payload, 66845, previous_schedule, allow_incomplete=partial).status == (
        'source_incomplete' if partial else 'imported')
    return series, payload, Path(raw_file), stage


def test_source_adapters_preserve_full_row_without_fabricating_daily_archive():
    row = _schedule_row()
    source = ScheduleSource([row])
    schedules, report = discover_series(source, datetime(2016, 2, 1))
    assert report['discovery_errors'] == [] and len(schedules) == 1
    assert schedules[0]['source_row'] == row == history_schedule(row, 1007, 'LPL')['source_row']
    assert schedules[0]['source_row']['other_source_field'] == {'kept': True}
    assert 'source_archive' not in schedules[0]


def test_history_schedule_uses_actual_stage_archive_and_legacy_has_no_source_row(db, tmp_path):
    series, _, _, stage = _prepared_result(db, tmp_path)
    series.raw_file = 'different-resultlist.json'
    schedule = series.schedule()
    assert schedule['source_row'] == _schedule_row()
    assert schedule['source_archive'] == {'raw_file': stage.raw_file, 'sha256': stage.raw_sha256}
    assert 'source_row' not in SyncTask(task_key='result:7', result_id=7).schedule()
    series.source_json = None
    assert 'source_row' not in series.schedule() and 'source_archive' not in series.schedule()


@pytest.mark.parametrize('changed', [False, True])
def test_stage_binding_changes_only_with_real_source_row_and_is_available_before_queue(db, tmp_path, monkeypatch, changed):
    series, _, _, old_stage = _prepared_result(db, tmp_path)
    new_stage = HistoryStage(tournament_id=1007, cache_key='12', parent_round_id=11)
    db.session.add(new_stage)
    db.session.commit()
    row = _schedule_row()
    if changed:
        row['team_short_name_b'] = '更正LGD'
    else:
        row = dict(reversed(list(row.items())))  # JSON 键顺序不是新的来源行。
    captured = []
    original_queue = history._queue_series_results

    def queue(current, raw_dir):
        captured.append(current.schedule())
        original_queue(current, raw_dir)

    monkeypatch.setattr(history, '_queue_series_results', queue)
    history._discover_stage(ScheduleSource([row]), new_stage, tmp_path / 'raw', datetime(2026, 10, 4))
    expected_stage = new_stage if changed else old_stage
    assert series.stage_id == expected_stage.id
    assert captured[0]['source_archive'] == {'raw_file': new_stage.raw_file, 'sha256': new_stage.raw_sha256}
    assert series.schedule_raw_file == new_stage.raw_file and series.schedule_raw_sha256 == new_stage.raw_sha256
    assert series.schedule()['source_row'] == row
    assert db.session.query(SyncTask).one().status == 'queued'


def test_whole_stage_conflict_keeps_raw_but_does_not_bind_or_mutate_series(db, tmp_path):
    series, _, _, stage = _prepared_result(db, tmp_path)
    other = HistoryTournament(tournament_id=2000, name='另一赛事')
    db.session.add(other)
    db.session.flush()
    other_stage = HistoryStage(tournament_id=2000, cache_key='2', parent_round_id=2)
    db.session.add(other_stage)
    db.session.flush()
    db.session.add(HistorySeries(series_id=888, tournament_id=2000, stage_id=other_stage.id))
    new_stage = HistoryStage(tournament_id=1007, cache_key='3', parent_round_id=3)
    db.session.add(new_stage)
    db.session.commit()
    rows = [{**_schedule_row(), 'matchID': '999'}, {**_schedule_row(), 'matchID': '888'}]
    with pytest.raises(SourceError, match='两个赛事'):
        history._discover_stage(ScheduleSource(rows), new_stage, tmp_path / 'raw', datetime(2026, 10, 4))
    db.session.rollback()
    assert db.session.get(HistorySeries, 999) is None and series.stage_id == stage.id
    assert new_stage.raw_file is None
    assert json.loads((tmp_path / 'raw' / 'history' / 'stages' / '1007' / '3.json').read_bytes()) == rows


@pytest.mark.parametrize('invalid', ['duplicate_series', 'invalid_score', 'wrong_structure'])
def test_failed_refresh_keeps_successful_stage_and_existing_match_archive_recheckable(db, tmp_path, invalid):
    series, payload, _, stage = _prepared_result(db, tmp_path)
    now = datetime(2026, 10, 4)
    history._discover_stage(ScheduleSource([_schedule_row()]), stage, tmp_path / 'raw', now)
    assert ingest_result(payload, 66845, series.schedule()).status == 'imported'
    original = Path(stage.raw_file)
    original_bytes, original_sha = original.read_bytes(), stage.raw_sha256
    previous_proof = copy.deepcopy(db.session.query(Match).one().team_name_provenance)
    if invalid == 'duplicate_series':
        bad_rows = [_schedule_row(), _schedule_row()]
    elif invalid == 'invalid_score':
        bad_rows = [{**_schedule_row(), 'team_a_win': 'bad-score'}]
    else:
        bad_rows = {'unpublished': True}
    with pytest.raises((SourceError, ValueError)):
        history._discover_stage(ScheduleSource(bad_rows), stage, tmp_path / 'raw', now)
    db.session.rollback()
    history._finish(stage, 'failed', '公开赛程校验失败')
    assert stage.raw_file == str(original) and stage.raw_sha256 == original_sha
    assert original.read_bytes() == original_bytes
    assert hashlib.sha256(original.read_bytes()).hexdigest() == previous_proof['schedule']['archive']['sha256']
    assert db.session.query(Match).one().team_name_provenance == previous_proof
    assert json.loads(series.source_json) == _schedule_row()
    failed = list((original.parent / 'failed-attempts').glob('p_11-*.json'))
    assert len(failed) == 1 and json.loads(failed[0].read_bytes()) == bad_rows
    assert ingest_result(payload, 66845, series.schedule()).status == 'imported'
    audit = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845])
    assert audit['blocked'] == 0 and audit['records'][0]['schedule_evidence']['source_archive']['sha256'] == original_sha


def test_successful_correction_uses_new_immutable_archive_and_preserves_prior_match_proof(db, tmp_path):
    series, payload, _, stage = _prepared_result(db, tmp_path)
    assert ingest_result(payload, 66845, series.schedule()).status == 'imported'
    original, original_sha = Path(stage.raw_file), stage.raw_sha256
    original_bytes = original.read_bytes()
    previous_proof = copy.deepcopy(db.session.query(Match).one().team_name_provenance)
    corrected = {**_schedule_row(), 'team_short_name_b': '更正LGD'}
    history._discover_stage(ScheduleSource([corrected]), stage, tmp_path / 'raw', datetime(2026, 10, 4))
    assert stage.raw_file != str(original) and stage.raw_sha256 != original_sha
    changed = Path(stage.raw_file)
    assert changed.name == f'p_11-{stage.raw_sha256}.json'
    assert json.loads(changed.read_bytes()) == [corrected]
    assert hashlib.sha256(changed.read_bytes()).hexdigest() == stage.raw_sha256
    assert series.stage_id == stage.id and series.schedule()['source_row'] == corrected
    assert series.schedule()['source_archive'] == {'raw_file': str(changed), 'sha256': stage.raw_sha256}
    assert original.read_bytes() == original_bytes
    assert hashlib.sha256(original.read_bytes()).hexdigest() == previous_proof['schedule']['archive']['sha256']
    assert db.session.query(Match).one().team_name_provenance == previous_proof
    assert db.session.query(SyncTask).one().status == 'queued'
    # 同一新版响应复用不可变文件，不再产生下一份更正归档。
    history._discover_stage(ScheduleSource([corrected]), stage, tmp_path / 'raw', datetime(2026, 10, 4))
    assert stage.raw_file == str(changed)
    assert len(list(original.parent.glob('p_11-*.json'))) == 1
    assert ingest_result(payload, 66845, series.schedule()).status == 'imported'
    match = db.session.query(Match).one()
    assert match.red_team_name == '更正LGD'
    assert match.team_name_provenance['schedule']['archive']['raw_file'] == str(changed)
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize('already_bound', [False, True])
def test_refresh_to_empty_preserves_omitted_series_version_including_first_migrated_null_binding(db, tmp_path, already_bound):
    series, payload, _, stage = _prepared_result(db, tmp_path)
    if already_bound:
        series.schedule_raw_file, series.schedule_raw_sha256 = stage.raw_file, stage.raw_sha256
        db.session.commit()
    else:
        assert series.schedule_raw_file is None and series.schedule_raw_sha256 is None
    assert ingest_result(payload, 66845, series.schedule()).status == 'imported'
    original, original_sha = Path(stage.raw_file), stage.raw_sha256
    old_proof = copy.deepcopy(db.session.query(Match).one().team_name_provenance)
    history._discover_stage(ScheduleSource([]), stage, tmp_path / 'raw', datetime(2026, 10, 4))
    assert json.loads(Path(stage.raw_file).read_bytes()) == [] and stage.raw_file != str(original)
    assert series.schedule_raw_file == str(original) and series.schedule_raw_sha256 == original_sha
    assert series.schedule()['source_archive'] == old_proof['schedule']['archive']
    assert series.schedule()['source_row'] == _schedule_row()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_sha
    assert ingest_result(payload, 66845, series.schedule()).status == 'imported'
    repaired = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], apply=True)
    assert repaired['applied'] == 1 and repaired['blocked'] == repaired['failed'] == 0
    assert repaired['records'][0]['schedule_evidence']['source_archive']['raw_file'] == str(original)


def test_failed_first_refresh_does_not_partially_bind_migrated_legacy_series(db, tmp_path):
    series, _, _, stage = _prepared_result(db, tmp_path)
    original_file, original_sha = stage.raw_file, stage.raw_sha256
    with pytest.raises(SourceError, match='重复'):
        history._discover_stage(ScheduleSource([_schedule_row(), _schedule_row()]), stage,
                                tmp_path / 'raw', datetime(2026, 10, 4))
    db.session.rollback()
    assert series.schedule_raw_file is None and series.schedule_raw_sha256 is None
    assert stage.raw_file == original_file and stage.raw_sha256 == original_sha
    assert hashlib.sha256(Path(original_file).read_bytes()).hexdigest() == original_sha
    assert series.schedule()['source_archive'] == {'raw_file': original_file, 'sha256': original_sha}


def test_refresh_omits_old_series_but_corrects_other_series_with_independent_versions(db, tmp_path):
    first, payload, _, stage = _prepared_result(db, tmp_path)
    second_row = {**_schedule_row(), 'matchID': '58147', 'team_short_name_a': '第二EDG', 'team_short_name_b': '第二LGD'}
    stage.raw_file, stage.raw_sha256 = history._archive(Path(stage.raw_file), [_schedule_row(), second_row])
    second = HistorySeries(series_id=58147, tournament_id=1007, stage_id=stage.id,
                           scheduled_at=first.scheduled_at, source_status='2', is_publist=1,
                           source_json=json.dumps(second_row), result_ids='[66846]', status='discovered')
    db.session.add(second)
    db.session.commit()
    assert first.schedule_raw_file is None and second.schedule_raw_file is None
    second_payload = copy.deepcopy(payload)
    second_payload['data']['resultID'], second_payload['data']['max_mvp']['match_id'] = '66846', '58147'
    second_payload['data']['max_beiguo']['match_id'] = '58147'
    history._archive(tmp_path / 'raw' / 'scoregg' / '66846.json', second_payload)
    assert ingest_result(payload, 66845, first.schedule()).status == 'imported'
    assert ingest_result(second_payload, 66846, second.schedule()).status == 'imported'
    original, original_sha = Path(stage.raw_file), stage.raw_sha256
    corrected = {**second_row, 'team_short_name_b': '第二更正LGD'}
    history._discover_stage(ScheduleSource([corrected]), stage, tmp_path / 'raw', datetime(2026, 10, 4))
    assert first.schedule_raw_file == str(original) and first.schedule_raw_sha256 == original_sha
    assert second.schedule_raw_file == stage.raw_file != str(original)
    assert second.schedule_raw_sha256 == stage.raw_sha256 != original_sha
    assert first.schedule()['source_archive']['raw_file'] == str(original)
    assert second.schedule()['source_archive']['raw_file'] == stage.raw_file
    assert first.schedule()['source_row'] == _schedule_row() and second.schedule()['source_row'] == corrected
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_sha
    assert ingest_result(payload, 66845, first.schedule()).status == 'imported'
    task = db.session.query(SyncTask).filter_by(result_id=66846).one()
    assert task.status == 'queued'
    outcome = history._fetch_task(ScheduleSource([]), task, tmp_path / 'raw', None, datetime(2026, 10, 4))
    assert outcome['status'] == 'imported' and outcome['reused_raw'] is True
    assert db.session.query(Match).filter_by(match_id=66846).one().red_team_name == '第二更正LGD'
    repaired = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845, 66846], apply=True)
    assert repaired['applied'] == 2 and repaired['blocked'] == repaired['failed'] == 0
    assert repaired['records'][0]['schedule_evidence']['source_archive']['raw_file'] == str(original)
    assert repaired['records'][1]['schedule_evidence']['source_archive']['raw_file'] == stage.raw_file


@pytest.mark.parametrize('invalid', ['missing_file', 'wrong_sha', 'missing_row', 'duplicate_row', 'invalid_json'])
def test_legacy_stage_fallback_without_valid_archive_does_not_manufacture_file_evidence(db, tmp_path, invalid):
    series, _, _, stage = _prepared_result(db, tmp_path)
    if invalid == 'missing_file':
        Path(stage.raw_file).unlink()
    elif invalid == 'wrong_sha':
        stage.raw_sha256 = '0' * 64
    elif invalid == 'missing_row':
        stage.raw_file, stage.raw_sha256 = history._archive(Path(stage.raw_file), [])
    elif invalid == 'duplicate_row':
        stage.raw_file, stage.raw_sha256 = history._archive(Path(stage.raw_file), [_schedule_row(), _schedule_row()])
    else:
        Path(stage.raw_file).write_bytes(b'not-json')
        stage.raw_sha256 = hashlib.sha256(b'not-json').hexdigest()
    db.session.commit()
    schedule = series.schedule()
    assert schedule['source_row'] == _schedule_row() and 'source_archive' not in schedule
    evidence = history._repair_schedule_evidence(schedule)
    assert evidence['source_archive'] is None and evidence['source_row'] == _schedule_row()
    assert evidence['series_archive_binding'] == {'raw_file': None, 'sha256': None}
    history._discover_stage(ScheduleSource([]), stage, tmp_path / 'raw', datetime(2026, 10, 4))
    assert series.schedule_raw_file is None and series.schedule_raw_sha256 is None
    assert 'source_archive' not in series.schedule()


def test_repair_without_recheckable_schedule_archive_still_blocks_changed_persisted_source_row(db, tmp_path, monkeypatch):
    series, _, _, stage = _prepared_result(db, tmp_path)
    stage.raw_file, stage.raw_sha256 = history._archive(Path(stage.raw_file), [])
    db.session.commit()
    audit = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845])
    assert audit['blocked'] == 0
    assert audit['records'][0]['schedule_evidence']['source_archive'] is None
    original_archive = history._archive
    wrote_plan = False

    def archive(path, payload):
        nonlocal wrote_plan
        archived = original_archive(path, payload)
        if not wrote_plan and Path(path).name.startswith('verified-raw-repair-'):
            wrote_plan = True
            series.source_json = json.dumps({**_schedule_row(), 'team_short_name_b': '变更标签'})
            db.session.commit()
        return archived

    monkeypatch.setattr(history, '_archive', archive)
    report = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0
    assert db.session.query(Match).one().red_team_name == 'LGD'


@pytest.mark.parametrize('partial', [False, True])
def test_complete_or_partial_cached_result_is_requeued_and_renamed_without_http(db, tmp_path, partial):
    series, _, raw, _ = _prepared_result(db, tmp_path, partial=partial)
    before_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    history._queue_series_results(series, tmp_path / 'raw')
    task = db.session.query(SyncTask).one()
    assert task.status == 'queued'
    outcome = history._fetch_task(ScheduleSource([]), task, tmp_path / 'raw', None, datetime(2026, 10, 4))
    assert outcome['reused_raw'] is True
    assert outcome['status'] == ('source_incomplete' if partial else 'imported')
    match = db.session.query(Match).one()
    assert (match.red_team_name, match.blue_team_name, match.win_team_name) == ('历史LGD', '历史EDG', '历史LGD')
    assert match.team_name_provenance['selected_source'] == 'schedule'
    assert match.team_name_provenance['detail']['archive']['sha256'] == before_hash
    assert {row.team_name for row in db.session.query(Team)} == {'历史LGD', '历史EDG'}
    assert {row.team_name for row in db.session.query(Player)} == {'历史LGD', '历史EDG'}
    assert db.session.query(Player).count() == (9 if partial else 10)
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == before_hash


@pytest.mark.parametrize('invalid', ['missing_bo', 'different_ids', 'missing_label', 'wrong_result', 'non_lol'])
def test_unproven_partial_name_candidate_is_not_requeued(db, tmp_path, invalid):
    series, payload, raw, _ = _prepared_result(db, tmp_path, partial=True)
    if invalid == 'missing_bo':
        payload['data']['max_mvp'].pop('match_id')
        payload['data']['max_beiguo'].pop('match_id')
    elif invalid == 'different_ids':
        payload['data']['result_list']['red_teamID'] = '999'
    elif invalid == 'missing_label':
        row = _schedule_row()
        row['team_short_name_b'] = ''
        series.source_json = json.dumps(row)
    elif invalid == 'wrong_result':
        payload['data']['resultID'] = '999'
    else:
        payload['data']['gameID'] = '2'
    raw.write_text(json.dumps(payload), encoding='utf-8')
    history._queue_series_results(series, tmp_path / 'raw')
    assert db.session.query(SyncTask).one().status == 'source_incomplete'
    assert db.session.query(Match).one().red_team_name == 'LGD'


def test_repair_freezes_two_sources_and_name_provenance_then_is_idempotent(db, tmp_path):
    series, _, raw, stage = _prepared_result(db, tmp_path, partial=True)
    original_detail, original_schedule = raw.read_bytes(), Path(stage.raw_file).read_bytes()
    audit = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845])
    item = audit['records'][0]
    assert audit['blocked'] == 0 and audit['applied'] == 0
    assert item['schedule_evidence']['stage_id'] == series.stage_id
    assert item['schedule_evidence']['source_row'] == _schedule_row()
    assert item['schedule_evidence']['source_archive']['sha256'] == hashlib.sha256(original_schedule).hexdigest()
    assert item['team_name_provenance']['before']['selected_source'] == 'detail'
    assert item['team_name_provenance']['after']['selected_source'] == 'schedule'
    applied = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], apply=True)
    assert applied['request_count'] == 0 and applied['applied'] == 1 and applied['blocked'] == applied['failed'] == 0
    assert len(Path(applied['journal_file']).read_text(encoding='utf-8').splitlines()) == 1
    assert db.session.query(Match).one().red_team_name == '历史LGD'
    repeat = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845])
    assert repeat['changed_fields'] == 0
    assert raw.read_bytes() == original_detail and Path(stage.raw_file).read_bytes() == original_schedule


@pytest.mark.parametrize('changed', ['detail_raw', 'schedule_raw', 'source_row', 'stage_id', 'archive_metadata',
                                   'series_archive_path', 'series_archive_sha'])
def test_repair_blocks_source_changes_after_plan_before_apply(db, tmp_path, monkeypatch, changed):
    series, _, raw, stage = _prepared_result(db, tmp_path)
    original_archive = history._archive
    wrote_plan = False

    def archive(path, payload):
        nonlocal wrote_plan
        archived = original_archive(path, payload)
        if not wrote_plan and Path(path).name.startswith('verified-raw-repair-'):
            wrote_plan = True
            if changed == 'detail_raw':
                raw.write_bytes(raw.read_bytes() + b' ')
            elif changed == 'schedule_raw':
                schedule_raw = Path(stage.raw_file)
                schedule_raw.write_bytes(schedule_raw.read_bytes() + b' ')
            elif changed == 'source_row':
                series.source_json = json.dumps({**_schedule_row(), 'team_short_name_b': '另一标签'})
                db.session.commit()
            elif changed == 'stage_id':
                replacement = HistoryStage(tournament_id=1007, cache_key='20', parent_round_id=20,
                                           raw_file=stage.raw_file, raw_sha256=stage.raw_sha256)
                db.session.add(replacement)
                db.session.flush()
                series.stage_id = replacement.id
                db.session.commit()
            elif changed == 'archive_metadata':
                stage.raw_sha256 = '0' * 64
                db.session.commit()
            elif changed == 'series_archive_path':
                series.schedule_raw_file = stage.raw_file
                db.session.commit()
            else:
                series.schedule_raw_sha256 = stage.raw_sha256
                db.session.commit()
        return archived

    monkeypatch.setattr(history, '_archive', archive)
    report = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0 and report['failed'] == 0
    assert report['records'][0]['status'] == 'blocked'
    assert db.session.query(Match).one().red_team_name == 'LGD'
    assert db.session.query(Player).count() == 10


def test_repair_rejects_stage_archive_without_exact_source_row_before_plan(db, tmp_path):
    series, _, _, stage = _prepared_result(db, tmp_path)
    stage.raw_file, stage.raw_sha256 = history._archive(Path(stage.raw_file), [{**_schedule_row(), 'matchID': '999'}])
    series.schedule_raw_file, series.schedule_raw_sha256 = stage.raw_file, stage.raw_sha256
    db.session.commit()
    report = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0
    assert '未唯一包含' in report['records'][0]['error']


def test_unmapped_legacy_repair_keeps_detail_labels_without_manufactured_schedule(db, tmp_path):
    series, _, _, stage = _prepared_result(db, tmp_path)
    task = db.session.query(SyncTask).one()
    task.series_id = None
    match = db.session.query(Match).one()
    match.series_id, match.source, match.verified = None, 'legacy', False
    db.session.delete(series)
    db.session.delete(stage)
    db.session.commit()
    report = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], apply=True)
    assert report['applied'] == 1 and report['blocked'] == 0
    item = report['records'][0]
    assert item['schedule_evidence'] is None and 'source_row' not in item['schedule']
    assert item['team_name_provenance']['after']['selected_source'] == 'detail'
    assert db.session.query(Match).one().red_team_name == 'LGD'


def test_repair_of_verified_daily_record_without_history_series_matches_retained_name_policy(db, tmp_path):
    series, payload, raw, stage = _prepared_result(db, tmp_path)
    assert ingest_result(payload, 66845, series.schedule()).status == 'imported'
    task = db.session.query(SyncTask).one()
    task.series_id = None
    db.session.delete(series)
    db.session.delete(stage)
    db.session.commit()
    report = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845], apply=True)
    item = report['records'][0]
    assert report['applied'] == 1 and report['blocked'] == 0
    assert item['schedule_evidence'] is None and 'source_row' not in item['schedule']
    assert item['team_name_provenance']['after']['reason'] == 'previous_verified_schedule_same_series_and_team_ids'
    assert item['team_name_provenance']['after'] == db.session.query(Match).one().team_name_provenance
    assert db.session.query(Match).one().red_team_name == '历史LGD'
    repeated = history.repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[66845])
    assert repeated['changed_fields'] == 0 and raw.is_file()
