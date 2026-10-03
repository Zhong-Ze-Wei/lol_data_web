import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import create_app, db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.services import team_name_repair as repair
from app.services.ingestion import ingest_result, normalize_result
from scripts import repair_team_names as cli
from scripts.pipeline_lock import PipelineLock
from test_history_team_names import _prepared_result

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


@pytest.fixture
def case(tmp_path):
    path = tmp_path / "old's names.sqlite"
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{path.as_posix()}',
                      'DATA_DIR': tmp_path, 'AUTO_CREATE_DB': False, 'AI_API_KEY': ''})
    with app.app_context():
        db.create_all()
        series, payload, detail, stage = _prepared_result(db, tmp_path)
        match = db.session.query(Match).one()
        match.team_name_provenance = None
        match.game_time = 99999  # 不得通过整场 normalize 重放覆写。
        player = db.session.query(Player).first()
        player.atk_m, player.hits, player.pic = 123456.75, 654321, 'retained-photo'
        team = db.session.query(Team).first()
        team.mvp = '保留既有MVP'
        db.session.commit()
        namespace = SimpleNamespace(database=path, raw_dir=tmp_path / 'raw', reports=tmp_path / 'reports',
                                    app=app, result_id=66845, payload=payload, detail=detail,
                                    stage_file=Path(stage.raw_file), stage_id=stage.id, series_id=series.series_id)
        db.session.remove()
    yield namespace
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def sql(case, statement, parameters=()):
    with closing(sqlite3.connect(case.database)) as connection:
        connection.execute(statement, parameters)
        connection.commit()


def rows(case, table):
    with closing(sqlite3.connect(case.database.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY id')]


def snapshot(case):
    return {table: rows(case, table) for table in ('matches', 'teams', 'players')}


def run(case, **kwargs):
    return repair.repair_team_names(case.database, case.raw_dir, case.reports,
                                    result_ids=kwargs.pop('result_ids', [case.result_id]), **kwargs)


def assert_only_names_changed(before, after):
    allowed = {'matches': {'red_team_name', 'blue_team_name', 'win_team_name', 'team_name_provenance'},
               'teams': {'team_name'}, 'players': {'team_name'}}
    for table in before:
        assert len(before[table]) == len(after[table])
        for old, new in zip(before[table], after[table]):
            assert old['id'] == new['id']
            assert {key: value for key, value in old.items() if key not in allowed[table]} == {
                key: value for key, value in new.items() if key not in allowed[table]}


def test_default_audit_is_readonly_and_freezes_actual_rows_and_two_sources(case):
    before = snapshot(case)
    original_bytes = case.database.read_bytes()
    report = run(case)
    assert report['mode'] == 'audit' and report['changed'] == 1 and report['applied'] == 0
    item = report['records'][0]
    assert item['status'] == 'ready' and item['before'] == before
    assert item['schedule']['source_row'] in json.loads(case.stage_file.read_bytes())
    assert item['schedule']['detail_archive']['sha256'] == hashlib.sha256(case.detail.read_bytes()).hexdigest()
    assert item['schedule']['source_archive']['sha256'] == hashlib.sha256(case.stage_file.read_bytes()).hexdigest()
    assert snapshot(case) == before and case.database.read_bytes() == original_bytes
    assert not (case.database.parent / '.sync.lock').exists()
    assert not (case.database.parent / 'backups').exists()
    assert json.loads(Path(report['report_file']).read_text(encoding='utf-8'))['records'][0]['before'] == before


def test_apply_changes_only_names_and_proof_with_full_backup_and_noop_second_pass(case):
    before = snapshot(case)
    raw_before = case.detail.read_bytes(), case.stage_file.read_bytes()
    report = run(case, apply=True)
    assert report['applied'] == 1 and report['blocked'] == report['failed'] == 0
    after = snapshot(case)
    assert_only_names_changed(before, after)
    assert {row['team_name'] for row in after['teams']} == {'历史LGD', '历史EDG'}
    assert after['matches'][0]['red_team_name'] == '历史LGD'
    proof = json.loads(after['matches'][0]['team_name_provenance'])
    assert proof['status'] == 'verified' and proof['selected_source'] == 'schedule'
    backup = Path(report['backup']['file'])
    assert backup.name.startswith('repair-team-names-')
    assert backup not in set(backup.parent.glob('lol-data-*.db'))
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == report['backup']['sha256']
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert connection.execute('SELECT red_team_name FROM matches').fetchall() == [('LGD',)]
        assert connection.execute('SELECT team_name_provenance FROM matches').fetchall() == [(None,)]
    assert len(Path(report['journal_file']).read_text(encoding='utf-8').splitlines()) == 1
    second = run(case, apply=True)
    assert second['noop'] == 1 and second['changed'] == second['applied'] == 0
    assert 'backup' not in second and len(list(backup.parent.iterdir())) == 1
    assert snapshot(case) == after
    assert (case.detail.read_bytes(), case.stage_file.read_bytes()) == raw_before


def test_source_missing_nickname_does_not_erase_existing_recovered_player(case):
    payload = copy.deepcopy(case.payload)
    payload['data']['result_list']['blue_star_e_name'] = ''
    case.detail.write_text(json.dumps(payload), encoding='utf-8')
    sql(case, "UPDATE players SET name='已恢复昵称',pic='已恢复头像' WHERE team_name='EDG' AND position='e'")
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['applied'] == 1
    after = snapshot(case)
    assert_only_names_changed(before, after)
    assert len(after['players']) == 10
    assert any(row['name'] == '已恢复昵称' and row['pic'] == '已恢复头像' for row in after['players'])


@pytest.mark.parametrize('winner', [None, ''])
def test_unknown_winner_remains_unknown(case, winner):
    sql(case, 'UPDATE matches SET win_team_name=?', (winner,))
    assert run(case, apply=True)['applied'] == 1
    assert rows(case, 'matches')[0]['win_team_name'] == winner


def test_name_swap_avoids_unique_conflicts_and_preserves_primary_ids(case):
    source = json.loads(case.stage_file.read_bytes())
    source[0].update(team_short_name_a='LGD', team_short_name_b='EDG')
    encoded = json.dumps(source).encode()
    case.stage_file.write_bytes(encoded)
    sql(case, 'UPDATE history_stages SET raw_sha256=?', (hashlib.sha256(encoded).hexdigest(),))
    sql(case, 'UPDATE history_series SET source_json=?', (json.dumps(source[0]),))
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['applied'] == 1 and report['failed'] == 0
    after = snapshot(case)
    assert_only_names_changed(before, after)
    assert after['matches'][0]['red_team_name'] == 'EDG' and after['matches'][0]['blue_team_name'] == 'LGD'
    for old, new in zip(before['teams'] + before['players'], after['teams'] + after['players']):
        assert new['team_name'] == {'LGD': 'EDG', 'EDG': 'LGD'}[old['team_name']]


def test_verified_prior_ids_take_priority_when_current_detail_colors_swap_but_names_do_not(case):
    prior_row = json.loads(case.stage_file.read_bytes())[0]
    prior_row.update(team_short_name_a='EDG', team_short_name_b='LGD')
    previous = normalize_result(case.payload, case.result_id,
                                {'series_id': case.series_id, 'source_row': prior_row},
                                allow_incomplete=True)['matches'][0]['team_name_provenance']
    assert previous['status'] == 'verified'
    assert previous['detail']['team_ids'] == {'red': 17, 'blue': 1}
    assert previous['selected_names'] == {'red': 'LGD', 'blue': 'EDG'}
    sql(case, 'UPDATE matches SET team_name_provenance=?', (json.dumps(previous),))
    payload = copy.deepcopy(case.payload)
    payload['data']['result_list'].update(red_teamID='1', blue_teamID='17', red_result='0', blue_result='1')
    case.detail.write_text(json.dumps(payload), encoding='utf-8')
    before = snapshot(case)
    assert before['matches'][0]['red_team_name'] == 'LGD'
    assert before['matches'][0]['win_team_name'] == 'LGD'
    report = run(case, apply=True)
    assert report['applied'] == 1 and report['blocked'] == report['failed'] == 0
    after = snapshot(case)
    assert_only_names_changed(before, after)
    for table in ('teams', 'players'):
        for old, new in zip(before[table], after[table]):
            assert new['team_name'] == {'LGD': '历史LGD', 'EDG': '历史EDG'}[old['team_name']]
    assert after['matches'][0]['red_team_name'] == '历史EDG'
    assert after['matches'][0]['blue_team_name'] == '历史LGD'
    assert after['matches'][0]['win_team_name'] == '历史LGD'


@pytest.mark.parametrize('statement', [
    "UPDATE matches SET source='legacy'", "UPDATE matches SET verified=0",
    'UPDATE matches SET red_team_name=NULL', "UPDATE matches SET red_team_name='第三方队伍'",
    "UPDATE matches SET win_team_name='第三方队伍'", 'DELETE FROM teams WHERE id=(SELECT min(id) FROM teams)',
    "INSERT INTO teams(match_id,team_name) VALUES (66845,'第三方队伍')",
    'UPDATE teams SET team_name=NULL WHERE id=(SELECT min(id) FROM teams)',
    'UPDATE players SET team_name=NULL WHERE id=(SELECT min(id) FROM players)',
    "UPDATE players SET team_name='第三方队伍' WHERE id=(SELECT min(id) FROM players)",
    'UPDATE players SET position=NULL WHERE id=(SELECT min(id) FROM players)',
    "UPDATE players SET position='f' WHERE id=(SELECT min(id) FROM players)",
])
def test_unsafe_existing_identity_is_blocked_without_backup_or_deletion(case, statement):
    sql(case, statement)
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0 and 'backup' not in report
    assert snapshot(case) == before


@pytest.mark.parametrize('source', ['wrong_sha', 'missing_file', 'missing_row', 'duplicate_row', 'partial_binding', 'wrong_bo', 'wrong_ids'])
def test_unproven_or_conflicting_source_is_blocked_without_backup(case, source):
    if source == 'wrong_sha':
        sql(case, "UPDATE history_stages SET raw_sha256=?", ('0' * 64,))
    elif source == 'missing_file':
        case.stage_file.unlink()
    elif source in {'missing_row', 'duplicate_row'}:
        row = json.loads(case.stage_file.read_bytes())[0]
        encoded = json.dumps([] if source == 'missing_row' else [row, row]).encode()
        case.stage_file.write_bytes(encoded)
        sql(case, 'UPDATE history_stages SET raw_sha256=?', (hashlib.sha256(encoded).hexdigest(),))
    elif source == 'partial_binding':
        sql(case, 'UPDATE history_series SET schedule_raw_file=?', (str(case.stage_file),))
    else:
        payload = copy.deepcopy(case.payload)
        if source == 'wrong_bo':
            payload['data']['max_mvp']['match_id'] = '999'
        else:
            payload['data']['result_list']['red_teamID'] = '999'
        case.detail.write_text(json.dumps(payload), encoding='utf-8')
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0 and 'backup' not in report
    assert snapshot(case) == before


@pytest.mark.parametrize('source', ['detail_file', 'stage_file', 'source_row', 'binding', 'verified', 'player_stat'])
def test_apply_blocks_changes_after_plan_without_overwriting_concurrent_data(case, monkeypatch, source):
    write = repair._write_report
    injected = False

    def publish(path, report):
        nonlocal injected
        write(path, report)
        if injected:
            return
        injected = True
        if source == 'detail_file':
            case.detail.write_bytes(case.detail.read_bytes() + b' ')
        elif source == 'stage_file':
            case.stage_file.write_bytes(case.stage_file.read_bytes() + b' ')
        elif source == 'source_row':
            sql(case, "UPDATE history_series SET source_json='{}'")
        elif source == 'binding':
            sql(case, 'UPDATE history_series SET schedule_raw_file=?', (str(case.stage_file),))
        elif source == 'verified':
            sql(case, 'UPDATE matches SET verified=0')
        else:
            sql(case, 'UPDATE players SET hits=42 WHERE id=(SELECT min(id) FROM players)')

    monkeypatch.setattr(repair, '_write_report', publish)
    report = run(case, apply=True)
    assert report['applied'] == 0 and report['blocked'] + report['failed'] == 1
    assert rows(case, 'matches')[0]['red_team_name'] == 'LGD'
    if source == 'player_stat':
        assert rows(case, 'players')[0]['hits'] == 42


def test_database_trigger_cannot_silently_modify_numeric_fields(case):
    sql(case, '''CREATE TRIGGER change_stat AFTER UPDATE OF team_name ON players
                BEGIN UPDATE players SET hits=777 WHERE id=NEW.id; END''')
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0
    assert snapshot(case) == before


def test_proof_only_update_does_not_touch_unchanged_team_or_player_names(case):
    source = json.loads(case.stage_file.read_bytes())
    source[0].update(team_short_name_a='EDG', team_short_name_b='LGD')
    encoded = json.dumps(source).encode()
    case.stage_file.write_bytes(encoded)
    sql(case, 'UPDATE history_stages SET raw_sha256=?', (hashlib.sha256(encoded).hexdigest(),))
    sql(case, 'UPDATE history_series SET source_json=?', (json.dumps(source[0]),))
    sql(case, '''CREATE TRIGGER reject_unneeded_name_write BEFORE UPDATE OF team_name ON players
                BEGIN SELECT RAISE(ABORT,'should not write unchanged names'); END''')
    before = snapshot(case)
    report = run(case, apply=True)
    after = snapshot(case)
    assert report['applied'] == 1 and report['blocked'] == report['failed'] == 0
    assert before['teams'] == after['teams'] and before['players'] == after['players']
    assert json.loads(after['matches'][0]['team_name_provenance'])['status'] == 'verified'


def test_sql_failure_rolls_back_whole_game_and_continues_other_selected_game(case):
    with case.app.app_context():
        payload = copy.deepcopy(case.payload)
        payload['data']['resultID'] = '66846'
        assert ingest_result(payload, 66846, {'series_id': case.series_id}).status == 'imported'
        (case.raw_dir / 'scoregg' / '66846.json').write_text(json.dumps(payload), encoding='utf-8')
        db.session.remove()
    sql(case, '''CREATE TRIGGER reject_name BEFORE UPDATE OF team_name ON players WHEN OLD.match_id=66845
                BEGIN SELECT RAISE(ABORT,'isolated failure'); END''')
    before = snapshot(case)
    report = run(case, result_ids=[66845, 66846], apply=True)
    assert report['failed'] == report['applied'] == 1
    after = snapshot(case)
    for table in before:
        assert [row for row in before[table] if row['match_id'] == 66845] == [row for row in after[table] if row['match_id'] == 66845]
    assert [row for row in after['matches'] if row['match_id'] == 66846][0]['red_team_name'] == '历史LGD'
    assert len(Path(report['journal_file']).read_text(encoding='utf-8').splitlines()) == 2


def test_existing_prior_proof_is_revalidated_and_correct_record_is_noop(case):
    assert run(case, apply=True)['applied'] == 1
    sql(case, "UPDATE matches SET team_name_provenance=json_set(team_name_provenance,'$.reason','previous_verified_schedule_same_series_and_team_ids')")
    assert run(case, apply=True)['noop'] == 1


def test_correct_immutable_previous_proof_does_not_need_latest_archive_rewrite(case):
    first = run(case, apply=True)
    before = snapshot(case)
    original_row = json.loads(case.stage_file.read_bytes())[0]
    latest = case.stage_file.with_name('p_11-new-version.json')
    encoded = json.dumps([original_row, {**original_row, 'matchID': '999'}]).encode()
    latest.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    sql(case, 'UPDATE history_series SET schedule_raw_file=?,schedule_raw_sha256=?', (str(latest), digest))
    sql(case, 'UPDATE history_stages SET raw_file=?,raw_sha256=?', (str(latest), digest))
    again = run(case, apply=True)
    assert again['noop'] == 1 and 'backup' not in again
    assert snapshot(case) == before
    assert len(list(Path(first['backup']['file']).parent.iterdir())) == 1


def test_known_prior_team_ids_conflict_even_if_labels_happen_to_match(case):
    payload = json.loads(case.detail.read_bytes())
    with case.app.app_context():
        from app.services.ingestion import normalize_result

        proof = normalize_result(payload, case.result_id, allow_incomplete=True)['matches'][0]['team_name_provenance']
    proof['detail']['team_ids']['blue'] = 999
    sql(case, 'UPDATE matches SET team_name_provenance=?', (json.dumps(proof),))
    report = run(case, apply=True)
    assert report['blocked'] == 1 and '双方 ID' in report['records'][0]['error']


@pytest.mark.parametrize('known_side', ['red', 'blue'])
def test_partial_prior_known_id_conflict_is_blocked_even_if_detail_names_match(case, known_side):
    previous = normalize_result(case.payload, case.result_id, allow_incomplete=True)['matches'][0]['team_name_provenance']
    previous['detail']['team_ids'] = {'red': None, 'blue': None, known_side: 999}
    sql(case, 'UPDATE matches SET team_name_provenance=?', (json.dumps(previous),))
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0 and 'backup' not in report
    assert '双方 ID' in report['records'][0]['error']
    assert snapshot(case) == before


@pytest.mark.parametrize('detail', ['invalid-proof', {'team_ids': 'invalid-ids'}])
def test_malformed_prior_identity_proof_is_blocked_as_a_reported_game(case, detail):
    sql(case, 'UPDATE matches SET team_name_provenance=?', (json.dumps({'detail': detail}),))
    report = run(case, apply=True)
    assert report['blocked'] == 1 and '结构无效' in report['records'][0]['error']
    assert report['applied'] == 0 and 'backup' not in report


def test_duplicate_player_position_in_an_old_unconstrained_table_is_blocked(case):
    with closing(sqlite3.connect(case.database)) as connection:
        connection.executescript('''CREATE TABLE old_players AS SELECT * FROM players;
            DROP TABLE players;
            ALTER TABLE old_players RENAME TO players;
            UPDATE players SET position='a' WHERE team_name='LGD' AND position='b';''')
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['blocked'] == 1 and '重复 Player' in report['records'][0]['error']
    assert snapshot(case) == before and 'backup' not in report


@pytest.mark.parametrize('invalid', ['code', 'non_lol', 'result_id', 'raw_metric'])
def test_detail_normalization_is_required_before_names_can_be_changed(case, invalid):
    payload = copy.deepcopy(case.payload)
    if invalid == 'code':
        payload['code'] = 500
    elif invalid == 'non_lol':
        payload['data']['gameID'] = '2'
    elif invalid == 'result_id':
        payload['data']['resultID'] = '999'
    else:
        payload['data']['result_list']['red_star_a_hits'] = '-1'
    case.detail.write_text(json.dumps(payload), encoding='utf-8')
    before = snapshot(case)
    report = run(case, apply=True)
    assert report['blocked'] == 1 and report['applied'] == 0 and 'backup' not in report
    assert snapshot(case) == before


def test_explicit_series_archive_remains_valid_when_latest_stage_omits_old_series(case):
    digest = hashlib.sha256(case.stage_file.read_bytes()).hexdigest()
    sql(case, 'UPDATE history_series SET schedule_raw_file=?,schedule_raw_sha256=?', (str(case.stage_file), digest))
    latest = case.stage_file.with_name('p_11-latest.json')
    latest.write_bytes(b'[]')
    sql(case, 'UPDATE history_stages SET raw_file=?,raw_sha256=?', (str(latest), hashlib.sha256(b'[]').hexdigest()))
    report = run(case, apply=True)
    assert report['applied'] == 1 and report['blocked'] == 0
    assert report['records'][0]['schedule']['source_archive']['raw_file'] == str(case.stage_file)


def test_backup_reads_committed_wal_and_preserves_task_states(case):
    with closing(sqlite3.connect(case.database)) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("UPDATE matches SET mvp='WAL内已提交更正'")
        writer.commit()
        with closing(sqlite3.connect(case.database.as_uri() + '?immutable=1', uri=True)) as main_file:
            assert main_file.execute('SELECT mvp FROM matches').fetchone()[0] != 'WAL内已提交更正'
        report = run(case, apply=True)
        with closing(sqlite3.connect(report['backup']['file'])) as backup:
            assert backup.execute('SELECT mvp FROM matches').fetchone()[0] == 'WAL内已提交更正'
            old_tasks = backup.execute('SELECT * FROM sync_tasks').fetchall()
        with closing(sqlite3.connect(case.database)) as current:
            assert current.execute('SELECT * FROM sync_tasks').fetchall() == old_tasks


@pytest.mark.parametrize('ids', [[], [True], ['66845'], [0], [-1], {'result_ids': [66845]}])
def test_explicit_scope_requires_nonempty_integer_ids(case, ids):
    with pytest.raises(repair.TeamNameRepairError, match='显式'):
        run(case, result_ids=ids, apply=True)
    assert not (case.database.parent / 'backups').exists()


def test_real_lock_competition_prevents_plan_backup_and_database_write(case):
    before = snapshot(case)
    with PipelineLock(case.database.parent / '.sync.lock'):
        process = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'scripts.repair_team_names',
                                  '--database', str(case.database), '--raw-dir', str(case.raw_dir),
                                  '--reports-dir', str(case.reports), '--result-ids', str(case.result_id),
                                  '--apply', '--wait-seconds', '.01'],
                                 cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=10, **HIDDEN)
    assert process.returncode == 3, process.stderr
    assert json.loads(process.stdout)['status'] == 'already_running'
    assert snapshot(case) == before and not case.reports.exists()
    assert not (case.database.parent / 'backups').exists()


def test_cli_json_ids_file_defaults_to_audit_and_rejects_manifest_object(case, tmp_path):
    ids = tmp_path / 'ids.json'
    ids.write_text(json.dumps([case.result_id]))
    args = ['--database', str(case.database), '--raw-dir', str(case.raw_dir), '--reports-dir', str(case.reports),
            '--ids-file', str(ids)]
    before = snapshot(case)
    assert cli.main(args) == 0 and snapshot(case) == before
    ids.write_text(json.dumps({'candidates': [case.result_id]}))
    assert cli.main(args) == 2


@pytest.mark.parametrize('seconds', [-1, 61, float('inf'), float('nan')])
def test_wait_is_finite_and_bounded(case, seconds):
    with pytest.raises(repair.TeamNameRepairError, match='0–60'):
        run(case, apply=True, wait_seconds=seconds)
