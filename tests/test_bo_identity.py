"""九个真实来源身份投影；指标入库用另一个完整 fixture，不冒充原局指标。"""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.models.match import Match
from app.models.player import Player
from app.models.sync import SyncTask
from app.models.team import Team
from app.services import history
from app.services.team_name_repair import repair_team_names
from app.services.ingestion import InvalidResult, PendingResult, ingest_result, normalize_result
from app.services.team_names import resolve_bo_identity, resolve_team_names
from test_history_team_names import ScheduleSource, _prepared_result
from test_team_name_repair import case as repair_case  # noqa: F401 -- 注册共享临时文件库 fixture。
from test_team_name_repair import snapshot as repair_snapshot, sql as repair_sql


# 按 result/<result_id>.json 的实际身份字段投影，SHA 指完整原件而非此投影。
REAL_CASES = [
    (1258, 560, 'a6dac39d8ff51412eab62171fc50bf2f4ef8d8b450829ed38b82344e35c76fbf', [], '94',
     '94', '104', 'KDM', 'IMT', '96', '0', '1', '94', '104', 'KDM', 'Immortals'),
    (11291, 5091, 'cbaa0f661b1f489e5dd2ac361f182da5d6ead48a746f1bc1c37d51be2c9323cb', [], None,
     '315', '246', 'VT', 'SNS', '246', '0', '1', '246', '315', 'SNS', 'VT'),
    (16141, 7936, '36d37fec05ff25d39d3247acb51460fc020811fe52be63bee507d83d9bf16f34', [], None,
     '537', '542', 'FPB', 'IG.Y', '542', '0', '1', '542', '537', 'IG.Y', 'FPB'),
    (20179, 9110, '01a18a804ad7146e2b4f6a182ea42abdea5b0a6689e188d5d8402d41540d770e', [], '20',
     '20', '18', 'WE', 'IG', '18', '0', '1', '18', '20', 'IG', 'WE'),
    (20181, 7337, '201bc1e5ec69fe7456e1651f2a27cf4f689c893935e040faac4154795738355d', {}, '557',
     '129', '557', 'RYL', 'EP.HK', '129', '1', '0', '129', '557', 'RYL', 'EP.HK'),
    (20233, 10090, 'd8558dfd2efe86c8bc210abc0dc7be73adef44cf1d589ef83bf4313c789b1828', [], '200',
     '7', '200', 'T1', 'Gambit', '7', '1', '0', '704', '7', 'GAB', 'T1'),
    (20252, 10097, 'f57393a6174260fcd88c7e74671d1b27208e03d2582e2ec2faeb4870d0b0ba21', [], '9',
     '9', '2', 'AHQ', 'C9', '2', '0', '1', '2', '9', 'C9', 'AHQ'),
    (31518, 1596, 'cbd115cd3bb830991845304b74fabb2fc49cc5111e8109fd8f2685644cd87a79', {}, '14',
     '14', '93', 'TSM', 'TL', '93', '0', '1', '93', '14', 'TL', 'TSM'),
    (34676, 20674, 'ee6b8cbeb74c342517b5da3b820dfce7e99d7f75b53fe2f00b0ea6bee37ad7f0', {}, '1894',
     '1895', '1894', 'Epik', 'aAa', '1895', '1', '0', '1894', '1895', 'aAa', 'Epik'),
]
BLOCKED_REASONS = {1258: 'winner_team_identity_mismatch', 20233: 'team_identity_mismatch',
                   11291: 'missing_series_identity', 16141: 'missing_series_identity'}


def identity_projection(case):
    (result_id, series_id, sha, mvp, auxiliary_team, red_id, blue_id, red, blue, winner,
     red_result, blue_result, a_id, b_id, a, b) = case
    data = {'gameID': '1', 'max_mvp': copy.deepcopy(mvp),
            'max_beiguo': [] if auxiliary_team is None else {'match_id': str(series_id), 'teamID': auxiliary_team},
            'result_list': {'red_teamID': red_id, 'blue_teamID': blue_id, 'red_name': red, 'blue_name': blue,
                            'win_teamID': winner, 'red_result': red_result, 'blue_result': blue_result,
                            'teamID_a': a_id if result_id != 20233 else '200', 'teamID_b': b_id}}
    schedule = {'series_id': series_id,
                'source_row': {'matchID': str(series_id), 'teamID_a': a_id, 'teamID_b': b_id,
                               'team_short_name_a': a, 'team_short_name_b': b},
                'detail_archive': {'raw_file': f'scoregg/{result_id}.json', 'sha256': sha}}
    return data, schedule, {'red': red, 'blue': blue}


@pytest.fixture
def source():
    payload = json.loads((Path(__file__).parent / 'fixtures' / 'scoregg_result_66845.json').read_bytes())
    payload['data']['result_list'].update(red_teamID='17', blue_teamID='1')
    schedule = {'series_id': 58146,
                'source_row': {'matchID': '58146', 'teamID_a': '1', 'teamID_b': '17',
                               'team_short_name_a': '历史EDG', 'team_short_name_b': '历史LGD'}}
    return payload, schedule


def resolve(payload, schedule, previous=None):
    info = payload['data']['result_list']
    return resolve_team_names(payload['data'], schedule,
                              {side: info[f'{side}_name'] for side in ('red', 'blue')}, previous)


@pytest.mark.parametrize('case', REAL_CASES, ids=lambda case: str(case[0]))
def test_nine_actual_identity_projections_preserve_conflicts_and_record_real_anchor(case):
    data, schedule, names = identity_projection(case)
    frozen = copy.deepcopy((data, schedule))
    selected, proof = resolve_team_names(data, schedule, names)
    reason = BLOCKED_REASONS.get(case[0])
    if reason:
        assert proof['selected_source'] == 'detail' and proof['status'] == 'unresolved'
        assert proof['reason'] == reason and selected == names and 'side_mapping' not in proof
    else:
        assert proof['selected_source'] == 'schedule' and proof['status'] == 'verified'
        assert proof['detail']['series_id'] == case[1]
        assert proof['detail']['series_id_source'] == 'max_beiguo.match_id'
        assert proof['detail']['primary_series_id'] is None
        assert proof['policy_version'] == 2 and selected == names
    assert proof['detail']['archive'] == schedule['detail_archive']
    assert (data, schedule) == frozen


@pytest.mark.parametrize('case', REAL_CASES, ids=lambda case: str(case[0]))
def test_nine_identity_projections_use_same_bo_and_winner_rules_in_normalization(source, case):
    payload, _ = source
    data, schedule, _ = identity_projection(case)
    # 仅完整指标/十槽来自人工 fixture；本测试不声称重放九局真实指标。
    payload['data'].update({key: value for key, value in data.items() if key != 'result_list'})
    payload['data']['result_list'].update(data['result_list'])
    if case[0] == 1258:
        with pytest.raises(InvalidResult, match='胜方'):
            normalize_result(payload, 66845, schedule, allow_incomplete=True)
        return
    match = normalize_result(payload, 66845, schedule, allow_incomplete=True)['matches'][0]
    assert match['series_id'] == case[1] and match['mvp'] is None
    assert match['team_name_provenance']['reason'] == BLOCKED_REASONS.get(case[0], 'same_series_and_team_ids')


@pytest.mark.parametrize('block', ['absent', None, [], {}, {'nickname': '不代表BO'},
                                  {'match_id': None}, {'match_id': ''}, {'match_id': '  '}])
def test_only_missing_primary_allows_explicit_auxiliary_without_synthesizing_mvp(source, block):
    payload, schedule = source
    if block == 'absent':
        payload['data'].pop('max_mvp')
    else:
        payload['data']['max_mvp'] = copy.deepcopy(block)
    frozen = copy.deepcopy(payload)
    names, proof = resolve(payload, schedule)
    match = normalize_result(payload, 66845, schedule)['matches'][0]
    assert names == {'red': '历史LGD', 'blue': '历史EDG'}
    assert proof['detail']['series_id_source'] == 'max_beiguo.match_id'
    assert match['series_id'] == 58146 and payload == frozen
    assert match['mvp'] == (block.get('nickname') if isinstance(block, dict) else None)


@pytest.mark.parametrize('field', ['max_mvp', 'max_beiguo'])
@pytest.mark.parametrize('value', [0, -1, True, '58146.0', '５８１４６', 'wrong', [58146], {'value': 58146}])
def test_any_provided_malformed_bo_cannot_be_bypassed_by_the_other_source(source, field, value):
    payload, schedule = source
    payload['data'][field]['match_id'] = value
    names, proof = resolve(payload, schedule)
    assert names == {'red': 'LGD', 'blue': 'EDG'} and proof['status'] == 'unresolved'
    assert proof['reason'] == f'invalid_{field}_series_identity'
    assert proof['detail']['series_id'] is None and proof['detail']['series_id_source'] is None
    with pytest.raises(InvalidResult, match='BO'):
        normalize_result(payload, 66845, schedule)


@pytest.mark.parametrize('field', ['max_mvp', 'max_beiguo'])
@pytest.mark.parametrize('block', [[{'match_id': '58146'}], '58146', 0])
def test_malformed_nonempty_source_block_is_not_treated_as_missing(source, field, block):
    payload, schedule = source
    payload['data'][field] = block
    assert resolve(payload, schedule)[1]['status'] == 'unresolved'
    with pytest.raises(InvalidResult, match='BO'):
        normalize_result(payload, 66845, schedule)


def test_primary_has_priority_but_explicit_auxiliary_conflict_is_rejected(source):
    payload, schedule = source
    identity = resolve_bo_identity(payload['data'])
    assert identity['source'] == 'max_mvp.match_id' and identity['series_id'] == 58146
    payload['data']['max_beiguo']['match_id'] = '999'
    assert resolve(payload, schedule)[1]['reason'] == 'auxiliary_series_identity_mismatch'
    with pytest.raises(InvalidResult, match='BO'):
        normalize_result(payload, 66845, schedule)


def test_auxiliary_bo_cannot_take_the_series_id_from_schedule(source):
    payload, schedule = source
    payload['data']['max_mvp'] = []
    payload['data']['max_beiguo']['match_id'] = '999'
    assert resolve(payload, schedule)[1]['reason'] == 'series_identity_mismatch'
    with pytest.raises(InvalidResult, match='BO'):
        normalize_result(payload, 66845, schedule)


@pytest.mark.parametrize('winner', ['999', '1', '0', True, '17.0'])
def test_explicit_winner_must_belong_to_teams_and_match_final_color(source, winner):
    payload, schedule = source
    payload['data']['max_mvp'] = []
    payload['data']['result_list']['win_teamID'] = winner
    assert resolve(payload, schedule)[1]['status'] == 'unresolved'
    with pytest.raises(InvalidResult, match='胜方'):
        normalize_result(payload, 66845, schedule)


@pytest.mark.parametrize('red,blue', [('1.0', '0.0'), (1.0, 0.0), ('1e0', '0e0')])
def test_winner_crosscheck_uses_flags_as_accepted_by_existing_numeric_parser(source, red, blue):
    payload, schedule = source
    payload['data']['result_list'].update(red_result=red, blue_result=blue, win_teamID='1')
    names, proof = resolve(payload, schedule)
    assert names == {'red': 'LGD', 'blue': 'EDG'} and proof['status'] == 'unresolved'
    assert proof['reason'] == 'winner_result_mismatch'
    with pytest.raises(InvalidResult, match='winner_result_mismatch'):
        normalize_result(payload, 66845, schedule)


@pytest.mark.parametrize('red,blue', [('1.0', '0.0'), (1.0, 0.0), ('1e0', '0e0')])
def test_cached_opposite_winner_with_numeric_flags_is_not_requeued(db, tmp_path, red, blue):
    series, payload, raw, _ = _prepared_result(db, tmp_path)
    payload['data']['result_list'].update(red_result=red, blue_result=blue, win_teamID='1')
    raw.write_text(json.dumps(payload), encoding='utf-8')
    original = raw.read_bytes()
    match = db.session.query(Match).one()
    task = db.session.query(SyncTask).one()
    assert task.status == 'imported'
    assert history._cached_team_names_changed(match, series.schedule(), raw) is False
    history._queue_series_results(series, tmp_path / 'raw')
    assert task.status == 'imported'
    assert match.red_team_name == 'LGD' and match.blue_team_name == 'EDG'
    assert raw.read_bytes() == original


@pytest.mark.parametrize('winner', [None, '', '  '])
def test_absent_winner_is_not_filled_or_required_for_bo_names(source, winner):
    payload, schedule = source
    payload['data']['max_mvp'] = []
    payload['data']['result_list']['win_teamID'] = winner
    frozen = copy.deepcopy(payload)
    assert resolve(payload, schedule)[1]['status'] == 'verified'
    assert normalize_result(payload, 66845, schedule)['matches'][0]['series_id'] == 58146
    assert payload == frozen


def test_unfinished_result_keeps_pending_instead_of_treating_zero_winner_as_final_error(source):
    payload, schedule = source
    payload['data']['result_list'].update(win_teamID='0', red_result='0', blue_result='0')
    with pytest.raises(PendingResult, match='尚未确定'):
        normalize_result(payload, 66845, schedule)


def test_placeholder_duration_keeps_strict_pending_but_does_not_allow_partial_conflicting_winner(source):
    payload, schedule = source
    payload['data']['result_list'].update(game_time_m='0', game_time_s='01', win_teamID='999')
    with pytest.raises(PendingResult, match='时长'):
        normalize_result(payload, 66845, schedule)
    with pytest.raises(InvalidResult, match='胜方'):
        normalize_result(payload, 66845, schedule, allow_incomplete=True)


def test_auxiliary_without_schedule_can_declare_bo_but_cannot_invent_schedule_names(source):
    payload, _ = source
    payload['data']['max_mvp'] = []
    match = normalize_result(payload, 66845)['matches'][0]
    assert match['series_id'] == 58146 and match['mvp'] is None
    assert match['red_team_name'] == 'LGD' and match['blue_team_name'] == 'EDG'
    assert match['team_name_provenance']['reason'] == 'no_schedule_source'


def test_verified_v1_primary_proof_can_be_revalidated_with_auxiliary_anchor(source):
    payload, schedule = source
    _, previous = resolve(payload, schedule)
    previous['policy_version'] = 1
    previous['detail'].pop('series_id_source')
    previous['detail'].pop('primary_series_id')
    payload['data']['max_mvp'] = []
    names, proof = resolve(payload, {'series_id': 58146}, previous)
    assert names == previous['selected_names'] and proof['status'] == 'verified'
    assert proof['schedule'] == previous['schedule']
    assert proof['reason'] == 'previous_verified_schedule_same_series_and_team_ids'
    assert proof['policy_version'] == 2 and proof['detail']['series_id_source'] == 'max_beiguo.match_id'


@pytest.mark.parametrize('partial', [False, True])
def test_missing_mvp_cached_result_uses_actual_auxiliary_bo_and_requeues_without_http(db, tmp_path, partial):
    series, payload, raw, _ = _prepared_result(db, tmp_path, partial=partial)
    payload['data']['max_mvp'] = []
    raw.write_text(json.dumps(payload), encoding='utf-8')
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    history._queue_series_results(series, tmp_path / 'raw')
    task = db.session.query(SyncTask).one()
    assert task.status == 'queued'
    client = ScheduleSource([])
    outcome = history._fetch_task(client, task, tmp_path / 'raw', None, datetime(2026, 10, 4))
    assert outcome['reused_raw'] is True and client.calls == []
    assert outcome['status'] == ('source_incomplete' if partial else 'imported')
    match = db.session.query(Match).one()
    assert match.red_team_name == '历史LGD' and match.blue_team_name == '历史EDG'
    assert match.team_name_provenance['detail']['series_id_source'] == 'max_beiguo.match_id'
    assert match.team_name_provenance['detail']['archive']['sha256'] == digest
    assert db.session.query(Player).count() == (9 if partial else 10)
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == digest


def test_rejected_identity_does_not_modify_existing_business_rows(db, source):
    payload, schedule = source
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    before = {model: [{column.name: copy.deepcopy(getattr(row, column.name)) for column in model.__table__.columns}
                      for row in db.session.query(model).order_by(model.id)] for model in (Match, Team, Player)}
    payload['data']['max_mvp'] = []
    payload['data']['result_list']['win_teamID'] = '999'
    assert ingest_result(payload, 66845, schedule).status == 'failed'
    after = {model: [{column.name: copy.deepcopy(getattr(row, column.name)) for column in model.__table__.columns}
                     for row in db.session.query(model).order_by(model.id)] for model in (Match, Team, Player)}
    assert after == before


@pytest.fixture
def v1_unresolved_repair(repair_case):
    """按真实 v1 空 MVP/有效备用的证明结构，使用已存在的隔离文件库。"""
    payload = copy.deepcopy(repair_case.payload)
    payload['data']['max_mvp'] = []
    repair_case.detail.write_text(json.dumps(payload), encoding='utf-8')
    rows = json.loads(repair_case.stage_file.read_bytes())
    rows[0].update(team_short_name_a='EDG', team_short_name_b='LGD')
    encoded = json.dumps(rows).encode()
    repair_case.stage_file.write_bytes(encoded)
    schedule_digest = hashlib.sha256(encoded).hexdigest()
    repair_sql(repair_case, 'UPDATE history_stages SET raw_sha256=?', (schedule_digest,))
    repair_sql(repair_case, 'UPDATE history_series SET source_json=?', (json.dumps(rows[0]),))
    proof = normalize_result(payload, repair_case.result_id,
                             {'series_id': repair_case.series_id, 'source_row': rows[0],
                              'source_archive': {'raw_file': str(repair_case.stage_file), 'sha256': schedule_digest},
                              'detail_archive': {'raw_file': str(repair_case.detail),
                                                 'sha256': hashlib.sha256(repair_case.detail.read_bytes()).hexdigest()}},
                             allow_incomplete=True)['matches'][0]['team_name_provenance']
    # v1 只使用 max_mvp 声明 BO；备用另存 auxiliary，但不能补主锚点。
    proof.update(policy_version=1, selected_source='detail', status='unresolved', reason='missing_series_identity')
    proof['selected_names'] = dict(proof['detail']['names'])
    proof.pop('side_mapping')
    proof['detail']['series_id'] = None
    proof['detail'].pop('series_id_source')
    proof['detail'].pop('primary_series_id')
    repair_sql(repair_case, 'UPDATE matches SET team_name_provenance=?', (json.dumps(proof),))
    return repair_case


def test_v1_unknown_bo_with_same_detail_names_can_upgrade_only_proof_via_auxiliary(v1_unresolved_repair):
    case = v1_unresolved_repair
    before = repair_snapshot(case)
    report = repair_team_names(case.database, case.raw_dir, case.reports, result_ids=[case.result_id], apply=True)
    assert report['applied'] == 1 and report['blocked'] == report['failed'] == 0
    after = repair_snapshot(case)
    assert after['teams'] == before['teams'] and after['players'] == before['players']
    assert {key: value for key, value in after['matches'][0].items() if key != 'team_name_provenance'} == {
        key: value for key, value in before['matches'][0].items() if key != 'team_name_provenance'}
    proof = json.loads(after['matches'][0]['team_name_provenance'])
    assert proof['status'] == 'verified' and proof['policy_version'] == 2
    assert proof['detail']['series_id'] == case.series_id
    assert proof['detail']['series_id_source'] == 'max_beiguo.match_id'
    second = repair_team_names(case.database, case.raw_dir, case.reports, result_ids=[case.result_id], apply=True)
    assert second['noop'] == 1 and 'backup' not in second and repair_snapshot(case) == after


@pytest.mark.parametrize('conflict', ['unproven_name', 'different_positive_bo'])
def test_v1_unknown_bo_is_not_permission_to_bypass_name_or_explicit_bo_conflict(v1_unresolved_repair, conflict):
    case = v1_unresolved_repair
    if conflict == 'unproven_name':
        repair_sql(case, "UPDATE matches SET red_team_name='无证据旧名称'")
    else:
        proof = json.loads(repair_snapshot(case)['matches'][0]['team_name_provenance'])
        proof['detail']['series_id'] = 999
        repair_sql(case, 'UPDATE matches SET team_name_provenance=?', (json.dumps(proof),))
    before = repair_snapshot(case)
    report = repair_team_names(case.database, case.raw_dir, case.reports, result_ids=[case.result_id], apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0 and 'backup' not in report
    assert repair_snapshot(case) == before
