import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.models.match import Match
from app.models.sync import SyncTask
from app.services.spider import RequestBudget, SourceHTTPError
from scripts import pipeline


NOW = datetime(2026, 7, 23, 8)


def source_row(series_id=58146, **changes):
    return {'matchID': str(series_id), 'match_date': '2026-07-22', 'match_time': '17:00',
            'status': '2', 'is_publist': 1, 'team_a_win': '1', 'team_b_win': '2',
            'teamID_a': '1', 'teamID_b': '17', 'team_short_name_a': 'EDG',
            'team_short_name_b': 'LGD', **changes}


class DailySource:
    def __init__(self, stage_rows, *, payload=None, result_error=True):
        self.stage_rows = stage_rows
        self.payload = payload
        self.result_error = result_error
        self.budget = RequestBudget(40, 60)
        self.calls = []

    def get(self, url):
        self.budget.reserve()
        self.calls.append(url)
        page = {'gameID': '1', 'tournament_list': [
            {'tournamentID': '1007', 'name': 'LPL', 'start_date': '2026-07-01',
             'end_date': '2026-07-31'}]}
        return type('Page', (), {'text': 'var t_data = ' + json.dumps(page) + ';'})()

    def get_json(self, url):
        self.budget.reserve()
        self.calls.append(url)
        if '/tr/' in url:
            return [{'roundID': '2255', 'round_son': [{'id': key} for key in self.stage_rows]}]
        key = url.removeprefix('https://img.scoregg.com/tr_round/').removesuffix('.json')
        return copy.deepcopy(self.stage_rows[key])

    def get_result_ids(self, series_id):
        self.budget.reserve()
        self.calls.append(('resultlist', series_id))
        if self.result_error:
            raise SourceHTTPError(f'https://img.scoregg.com/match/resultlist/{series_id}.json', 404)
        return [66845] if self.payload is not None else []

    def get_result(self, result_id):
        self.budget.reserve()
        self.calls.append(('result', result_id))
        return copy.deepcopy(self.payload)


def run_daily(source, tmp_path):
    return pipeline.run_pipeline('daily', client=source, now=NOW,
                                 raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')


def read_archive(reference):
    encoded = Path(reference['raw_file']).read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == reference['sha256']
    return json.loads(encoded)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def test_finished_pub1_404_retains_full_stage_source_and_failure_context(db, tmp_path):
    row = source_row()
    outside_window = source_row(59000, match_date='2026-07-24', status='0')
    source = DailySource({'3100': [row, outside_window]})
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['status'] == 'partial' and report['failed'] == 1
    assert db.session.query(SyncTask).one().status == 'failed'
    snapshot = report['details']['schedule_snapshot']
    assert snapshot['status'] == 'complete' and snapshot['archive_basis'] == 'parsed_source_canonical_json'
    assert len(snapshot['sources']) == 1
    stage = snapshot['sources'][0]
    assert stage['source_url'] == 'https://img.scoregg.com/tr_round/3100.json'
    assert stage['source_cache_key'] == '3100' and stage['source_parent_round_id'] == '2255'
    assert read_archive(stage['source_archive']) == [row, outside_window]
    assert stage['selected_series_ids'] == [58146]
    context = report['details']['outcomes'][0]['schedule_evidence']
    assert context['source_archive'] == stage['source_archive']
    assert context['canonical_row_sha256'] == canonical_sha(row)
    assert context['source_status'] == '2' and context['is_publist'] == 1
    assert context['series_score'] == ['1', '2']
    assert context['scheduled_at'] == '2026-07-22T17:00:00'
    assert context['source_url'] == stage['source_url']
    assert 'source_row' not in context and 'rows' not in json.dumps(report)
    assert ('resultlist', 58146) in source.calls
    assert read_archive(snapshot['manifest'])['run_id'] == report['run_id']


def test_actual_pub0_keeps_pending_and_archives_without_result_requests(db, tmp_path):
    row = source_row(is_publist=0)
    source = DailySource({'3100': [row]})
    report, code = run_daily(source, tmp_path)
    assert code == 0 and report['skipped'] == 1 and report['failed'] == 0
    assert db.session.query(SyncTask).one().status == 'pending'
    assert not any(isinstance(call, tuple) for call in source.calls)
    assert read_archive(report['details']['schedule_snapshot']['sources'][0]['source_archive']) == [row]
    assert report['details']['outcomes'][0]['schedule_evidence']['is_publist'] == 0


def test_missing_publication_flag_stays_unknown_in_404_evidence(db, tmp_path):
    row = source_row()
    del row['is_publist']
    report, code = run_daily(DailySource({'3100': [row]}), tmp_path)
    assert code == 2 and report['failed'] == 1
    assert report['details']['outcomes'][0]['schedule_evidence']['is_publist'] is None
    assert 'is_publist' not in read_archive(report['details']['schedule_snapshot']['sources'][0]['source_archive'])[0]


@pytest.mark.parametrize('changed_field', ['status', 'is_publist', 'teamID_a', 'team_short_name_a',
                                           'team_a_win', 'match_date'])
def test_business_conflict_between_stages_blocks_bo_and_preserves_both_sources(db, tmp_path, changed_field):
    different = {'status': '1', 'is_publist': 0, 'teamID_a': '9', 'team_short_name_a': '另一队',
                 'team_a_win': '2', 'match_date': '2026-07-21'}[changed_field]
    first = source_row()
    second = source_row(**{changed_field: different})
    # A later appearance must not revive a BO already known to conflict.
    source = DailySource({'3100': [first], '3101': [second], '3102': [first]})
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['status'] == 'partial'
    assert report['details']['discovery_errors']
    assert db.session.query(SyncTask).count() == 0
    assert not any(isinstance(call, tuple) for call in source.calls)
    snapshot = report['details']['schedule_snapshot']
    assert snapshot['conflicted_series_ids'] == [58146]
    assert len(snapshot['sources']) == 3
    assert sorted(canonical_sha(row) for stage in snapshot['sources']
                  for row in read_archive(stage['source_archive'])) == sorted(map(canonical_sha, [first, second, first]))


def test_equivalent_bo_from_two_stages_ignores_presentation_fields(db, tmp_path):
    first = source_row(live_url='https://example.test/a', title='第一标题')
    second = source_row(live_url='https://example.test/b', title='第二标题', teamID_a=1, is_publist='1')
    source = DailySource({'3100': [first], '3101': [second]})
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['failed'] == 1
    assert report['details']['discovery_errors'] == []
    assert source.calls.count(('resultlist', 58146)) == 1
    snapshot = report['details']['schedule_snapshot']
    assert snapshot['conflicted_series_ids'] == [] and len(snapshot['sources']) == 2
    context = report['details']['outcomes'][0]['schedule_evidence']
    rows = read_archive(context['source_archive'])
    assert sum(canonical_sha(row) == context['canonical_row_sha256'] for row in rows) == 1


def test_duplicate_bo_within_one_stage_cannot_claim_unique_row(db, tmp_path):
    row = source_row()
    source = DailySource({'3100': [row, copy.deepcopy(row)]})
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['details']['discovery_errors']
    assert db.session.query(SyncTask).count() == 0
    assert not any(isinstance(call, tuple) for call in source.calls)
    archive = report['details']['schedule_snapshot']['sources'][0]['source_archive']
    assert read_archive(archive) == [row, row]


def test_two_daily_runs_never_overwrite_old_snapshot_or_report(db, tmp_path):
    first, _ = run_daily(DailySource({'3100': [source_row(is_publist=0)]}), tmp_path)
    snapshot = first['details']['schedule_snapshot']
    paths = [snapshot['manifest']['raw_file'], *(stage['source_archive']['raw_file'] for stage in snapshot['sources'])]
    paths.append(str(tmp_path / 'reports' / f"{first['run_id']}.json"))
    original = {path: Path(path).read_bytes() for path in paths}
    second, _ = run_daily(DailySource({'3100': [source_row(is_publist=0, team_a_win='3')]}), tmp_path)
    assert second['run_id'] != first['run_id']
    assert second['details']['schedule_snapshot']['sources'][0]['source_archive']['raw_file'] not in original
    assert all(Path(path).read_bytes() == encoded for path, encoded in original.items())


@pytest.mark.parametrize('failed_file', ['manifest.json', 'stage-0002.json'])
def test_archive_failure_stops_before_all_result_requests_and_ingestion(db, tmp_path, monkeypatch, failed_file):
    source = DailySource({'3100': [source_row()], '3101': [source_row(58147)]}, result_error=False)
    original = Path.open

    def reject_daily_archive(path, mode='r', *args, **kwargs):
        if 'daily' in path.parts and path.name == failed_file and mode in ('wb', 'xb'):
            raise OSError('simulated daily evidence disk failure')
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', reject_daily_archive)
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['status'] == 'failed'
    assert 'simulated daily evidence disk failure' in report['error']
    assert report['details']['schedule_snapshot']['status'] == 'incomplete'
    assert not any(isinstance(call, tuple) for call in source.calls)
    assert db.session.query(SyncTask).count() == 0 and db.session.query(Match).count() == 0
    assert (tmp_path / 'reports' / f"{report['run_id']}.json").exists()
    if failed_file == 'stage-0002.json':
        snapshot = report['details']['schedule_snapshot']
        assert len(snapshot['sources']) == 1
        manifest = read_archive(snapshot['manifest'])
        assert manifest['file_verification_required'] is True and len(manifest['planned_sources']) == 2
        assert 'expected_sha256' in manifest['planned_sources'][1]['expected_archive']
        assert not Path(manifest['planned_sources'][1]['expected_archive']['raw_file']).exists()


def test_imported_provenance_uses_real_unique_stage_archive(db, tmp_path):
    payload = json.loads((Path(__file__).parent / 'fixtures/scoregg_result_66845.json').read_bytes())
    payload['data']['result_list'].update(red_teamID='17', blue_teamID='1', win_teamID='17')
    source = DailySource({'3100': [source_row()]}, payload=payload, result_error=False)
    report, code = run_daily(source, tmp_path)
    assert code == 0 and report['imported'] == 1
    proof = db.session.query(Match).one().team_name_provenance
    assert proof['selected_source'] == 'schedule' and proof['status'] == 'verified'
    stage = report['details']['schedule_snapshot']['sources'][0]
    assert proof['schedule']['archive'] == stage['source_archive']
    rows = read_archive(proof['schedule']['archive'])
    assert sum(canonical_sha(row) == proof['schedule']['canonical_row_sha256'] for row in rows) == 1


def test_a_b_swap_with_matching_ids_names_and_scores_is_equivalent(db, tmp_path):
    original = source_row()
    swapped = source_row(teamID_a='17', teamID_b='1', team_short_name_a='LGD', team_short_name_b='EDG',
                         team_a_win='2', team_b_win='1', match_time='17:00:00')
    source = DailySource({'3100': [original], '3101': [swapped]})
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['failed'] == 1
    assert report['details']['discovery_errors'] == []
    assert source.calls.count(('resultlist', 58146)) == 1
    assert len(report['details']['schedule_snapshot']['sources']) == 2


def test_same_row_in_two_different_tournaments_is_a_binding_conflict(db, tmp_path):
    class TwoTournaments(DailySource):
        def get(self, url):
            page = {'gameID': '1', 'tournament_list': [
                {'tournamentID': str(tid), 'name': str(tid), 'start_date': '2026-07-01',
                 'end_date': '2026-07-31'} for tid in (1007, 1008)]}
            self.budget.reserve()
            self.calls.append(url)
            return type('Page', (), {'text': 'var t_data = ' + json.dumps(page) + ';'})()

        def get_json(self, url):
            self.budget.reserve()
            self.calls.append(url)
            if '/tr/' in url:
                tid = url.rsplit('/', 1)[1].removesuffix('.json')
                return [{'roundID': tid, 'round_son': []}]
            return [source_row()]

    source = TwoTournaments({})
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['details']['discovery_errors']
    assert not any(isinstance(call, tuple) for call in source.calls)
    assert db.session.query(SyncTask).count() == 0
    snapshots = report['details']['schedule_snapshot']['sources']
    assert {s['tournament_id'] for s in snapshots} == {1007, 1008}
    assert all(read_archive(s['source_archive']) == [source_row()] for s in snapshots)


def test_conflicted_bo_does_not_block_other_independent_pending_series(db, tmp_path):
    source = DailySource({'3100': [source_row(), source_row(58147, is_publist=0)],
                          '3101': [source_row(team_a_win='3')]})
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['status'] == 'partial' and report['skipped'] == 1
    task = db.session.query(SyncTask).one()
    assert task.series_id == 58147 and task.status == 'pending'
    assert not any(isinstance(call, tuple) for call in source.calls)
    assert report['details']['schedule_snapshot']['conflicted_series_ids'] == [58146]


@pytest.mark.parametrize('outside_date', ['2026-07-24', '2026-07-01'])
@pytest.mark.parametrize('same_stage', [True, False])
def test_selected_bo_checks_outside_window_competitor_and_later_third_source(db, tmp_path, outside_date, same_stage):
    selected = source_row()
    competing = source_row(match_date=outside_date, status='0', is_publist=0)
    stages = {'3100': [selected, competing] if same_stage else [selected], '3102': [selected]}
    if not same_stage:
        stages['3101'] = [competing]
    source = DailySource(stages)
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['status'] == 'partial'
    assert report['details']['schedule_snapshot']['conflicted_series_ids'] == [58146]
    assert db.session.query(SyncTask).count() == 0
    assert not any(isinstance(call, tuple) for call in source.calls)
    saved_rows = [row for stage in report['details']['schedule_snapshot']['sources']
                  for row in read_archive(stage['source_archive'])]
    assert saved_rows.count(competing) == 1 and saved_rows.count(selected) == 2


def test_unrelated_outside_window_bo_does_not_expand_daily_scope(db, tmp_path):
    selected = source_row(is_publist=0)
    future = source_row(58147, match_date='2026-07-24', teamID_a='9', status='0')
    ancient = source_row(58148, match_date='2026-07-01', teamID_b='8')
    source = DailySource({'3100': [selected, future], '3101': [ancient]})
    report, code = run_daily(source, tmp_path)
    assert code == 0 and report['details']['discovery_errors'] == []
    task = db.session.query(SyncTask).one()
    assert task.series_id == 58146 and task.status == 'pending'
    assert not any(isinstance(call, tuple) for call in source.calls)
    assert report['details']['schedule_snapshot']['selected_series_count'] == 1
    assert len(report['details']['schedule_snapshot']['sources']) == 2


@pytest.mark.parametrize('phase', ['resultlist_time', 'detail_requests'])
def test_budget_interrupt_after_snapshot_retains_evidence_and_original_queued_tasks(db, tmp_path, phase):
    clock = [0.0]
    payload = json.loads((Path(__file__).parent / 'fixtures/scoregg_result_66845.json').read_bytes())
    payload['data']['result_list'].update(red_teamID='17', blue_teamID='1', win_teamID='17')

    class LimitedSource(DailySource):
        def get_result_ids(self, series_id):
            if phase == 'resultlist_time':
                clock[0] = 60.0
            result_ids = super().get_result_ids(series_id)
            return list(range(66845, 66854)) if phase == 'detail_requests' else result_ids

        def get_result(self, result_id):
            result = super().get_result(result_id)
            result['data']['resultID'] = str(result_id)
            return result

    source = LimitedSource({'3100': [source_row()]}, payload=payload, result_error=False)
    source.budget = RequestBudget(12 if phase == 'detail_requests' else 40, 60, clock=lambda: clock[0])
    report, code = run_daily(source, tmp_path)
    assert code == 2 and report['status'] == 'budget_exhausted'
    assert report['request_count'] == (12 if phase == 'detail_requests' else 3)
    imported = 8 if phase == 'detail_requests' else 0
    assert report['imported'] == imported and db.session.query(Match).count() == imported
    snapshot = report['details']['schedule_snapshot']
    assert snapshot['status'] == 'complete'
    assert read_archive(snapshot['sources'][0]['source_archive']) == [source_row()]
    assert read_archive(snapshot['manifest'])['run_id'] == report['run_id']
    queued = db.session.query(SyncTask).filter_by(status='queued').one()
    assert queued.result_id == (66853 if phase == 'detail_requests' else None)
    assert queued.failure_count == 0 and queued.next_retry_at is None
    assert queued.last_error and not any(call == ('result', 66853) for call in source.calls)
    assert all(match.team_name_provenance['schedule']['archive'] == snapshot['sources'][0]['source_archive']
               for match in db.session.query(Match).all())


@pytest.mark.parametrize(('status', 'expected_result_calls'), [('0', 0), ('1', 1)])
def test_existing_waiting_and_ongoing_404_pending_semantics_remain(db, tmp_path, status, expected_result_calls):
    source = DailySource({'3100': [source_row(status=status)]})
    report, code = run_daily(source, tmp_path)
    assert code == 0 and report['failed'] == 0 and report['skipped'] == 1
    assert db.session.query(SyncTask).one().status == 'pending'
    assert source.calls.count(('resultlist', 58146)) == expected_result_calls
    assert report['details']['outcomes'][0]['schedule_evidence']['source_status'] == status


def test_untrusted_source_cache_key_is_metadata_never_a_local_path(db, tmp_path):
    source = DailySource({'../../outside': [source_row(is_publist=0)]})
    report, code = run_daily(source, tmp_path)
    assert code == 0
    snapshot = report['details']['schedule_snapshot']
    stage = snapshot['sources'][0]
    assert stage['source_cache_key'] == '../../outside'
    assert Path(stage['source_archive']['raw_file']).parent == Path(snapshot['directory'])
    assert Path(stage['source_archive']['raw_file']).name == 'stage-0001.json'
    assert read_archive(stage['source_archive']) == [source_row(is_publist=0)]


def test_retry_old_series_task_keeps_unknown_source_without_fabricating_archive(db, tmp_path):
    db.session.add(SyncTask(task_key='series:58146', series_id=58146, tournament_id=1007,
                            status='failed', attempts=1, failure_count=1))
    db.session.commit()
    source = DailySource({})
    report, code = pipeline.run_pipeline('retry', client=source, force=True,
                                         raw_dir=tmp_path / 'raw', reports_dir=tmp_path / 'reports')
    assert code == 2 and report['failed'] == 1
    assert 'schedule_snapshot' not in report['details']
    assert 'schedule_evidence' not in report['details']['outcomes'][0]
    assert db.session.query(SyncTask).one().failure_count == 2
    assert not (tmp_path / 'raw/daily').exists()
