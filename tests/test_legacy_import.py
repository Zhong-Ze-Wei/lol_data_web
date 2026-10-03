import csv
import json

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import SyncTask
from app.services.legacy_import import import_legacy, parse_legacy_duration, parse_player_row
from scripts.pipeline import run_pipeline


def player23(name='Player', match_id=1, team='A', position='a', side='red', result='1'):
    return [name, '2.5', '2', '2', '3', '50', '10000', '25', '250', '20000', '30', '500',
            '8.5', '15000', '400', '0', '200', str(match_id), team, position, side, '3410', result]


def player26(row):
    return row[:6] + ['10k'] + row[6:9] + ['20k'] + row[9:13] + ['15k'] + row[13:]


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        csv.writer(handle).writerows(rows)


def test_mixed_23_and_26_columns_have_identical_business_semantics():
    row = player23()
    assert len(player26(row)) == 26
    assert parse_player_row(row) == parse_player_row(player26(row))
    assert parse_player_row(row)['game_time'] == 2050


def test_legacy_duration_decodes_minutes_and_two_digit_seconds():
    assert parse_legacy_duration('3410') == 2050
    assert parse_legacy_duration('950') == 590
    assert parse_legacy_duration('005') == 5
    assert parse_legacy_duration('3460') is None
    assert parse_legacy_duration('') is None
    row = player23()
    row[-2] = '3490'
    parsed = parse_player_row(row)
    assert parsed['game_time'] is None
    assert parsed['_issues'][0]['raw_value'] == '3490'


def test_bulk_legacy_import_is_idempotent_and_reports_unverified(db, tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    teams = [[1, 'A', 1, '20240123140526', 'Player', '3410', 2, 1, 8, 20, 10, 40, 60000],
             [1, 'B', 0, '20240123140526', 'Player', '3410', 1, 0, 3, 10, 20, 20, 50000]]
    players = [player23(team=team, position=pos, side=side, result=result)
               for team, side, result in [('A', 'red', '1'), ('B', 'blue', '0')] for pos in 'abcde']
    write_csv(raw / 'team_data.csv', teams + teams)
    write_csv(raw / 'player_data.csv', players + [player26(row) for row in players])
    write_csv(raw / 'all.csv', [['No match ID']])
    first = import_legacy(raw)
    second = import_legacy(raw)
    assert first['duplicate_rows'] == second['duplicate_rows'] == 12
    assert db.session.query(Match).count() == 1
    assert db.session.query(Team).count() == 2
    assert db.session.query(Player).count() == 10
    match = db.session.query(Match).one()
    assert match.source == 'legacy' and not match.verified
    assert match.date_source == 'updated_at' and match.game_time == 2050
    assert first['issues']['unverified_game'] == 1
    assert first['issues']['no_match_id'] == 1
    assert all(len(item['sha256']) == 64 for item in first['files'])


def test_conflicting_natural_key_is_reported_without_taking_first(db, tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    original = player23()
    conflicting = original.copy()
    conflicting[2] = '9'
    valid_other = player23(name='Other', team='B', side='blue', result='0')
    write_csv(raw / 'player_data.csv', [original, conflicting, valid_other])
    report = import_legacy(raw)
    assert db.session.query(Player).count() == 1
    assert db.session.query(Player).one().name == 'Other'
    issues = [json.loads(line) for line in open(report['issues_file'], encoding='utf-8')]
    conflict = next(issue for issue in issues if issue['kind'] == 'conflicting_natural_key')
    assert conflict['first']['line'] == 1 and conflict['other']['line'] == 2
    assert report['issues']['missing_sides'] == 1


def test_missing_historical_players_are_retained_without_fabricating_rows(db, tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    write_csv(raw / 'team_data.csv', [[1, 'A', 1, '20240123140526', '', '3410', 2, 1, 8, 20, 10, 40, 60000]])
    report = import_legacy(raw)
    match = db.session.query(Match).one()
    assert match.red_team_name is None and match.blue_team_name is None
    assert db.session.query(Team).count() == 1
    assert db.session.query(Player).count() == 0
    assert report['issues']['missing_players'] == 1
    assert report['issues']['unknown_side_assignment'] == 1


def test_source_hash_skips_unchanged_import_and_force_can_reparse(db, tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    write_csv(raw / 'player_data.csv', [player23()])
    first, code = run_pipeline('import-legacy', data_dir=raw, reports_dir=tmp_path / 'reports')
    assert code == 0 and first['imported'] == 1
    second, code = run_pipeline('import-legacy', data_dir=raw, reports_dir=tmp_path / 'reports')
    assert code == 0 and second['imported'] == 0
    assert second['details']['legacy']['status'] == 'unchanged'
    third, code = run_pipeline('import-legacy', data_dir=raw, reports_dir=tmp_path / 'reports', force=True)
    assert code == 0 and third['imported'] == 1
    assert db.session.query(Player).count() == 1


def test_confirmed_non_lol_audit_prevents_reimport(db, tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    write_csv(raw / 'player_data.csv', [player23()])
    db.session.add(SyncTask(task_key='result:1', result_id=1, status='skipped', last_error='gameID=2，非LOL'))
    db.session.commit()
    report = import_legacy(raw)
    assert report['excluded_non_lol_matches'] == 1
    assert db.session.query(Match).count() == 0
    assert db.session.query(Player).count() == 0
