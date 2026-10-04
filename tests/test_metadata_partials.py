"""真实 35121 基础字段投影；完整升级用明确标记的合成 CDN 角色字段。"""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import SyncTask
from app.services import history, ingestion, spider
from app.services.metadata_snapshot import normalize_metadata_snapshot
from scripts import pipeline
from test_resultlist_fallback import NOW, response, series_fixture, source


@pytest.fixture
def stats():
    encoded = (Path(__file__).parent / 'fixtures/scoregg_bo20839_metadata_stats.json').read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == '955722931d4f58d5246a7ed28088457c9ec222218bc63a906e65cd61340041f7'
    return json.loads(encoded)


def ready(db, tmp_path, stats):
    series, raw_dir = series_fixture(db, tmp_path)
    client, _, _ = source(response(status=404), response(stats))
    discovered = history._discover_resultlist(client, series, raw_dir, NOW)
    evidence = discovered['resultlist_evidence']
    archive = {key: evidence[key] for key in ('raw_file', 'sha256', 'evidence_file')}
    return series, raw_dir, archive


def business_rows(db):
    return {model.__tablename__: [tuple(getattr(row, column.key) for column in model.__table__.columns)
                                  for row in db.session.query(model).order_by(model.id)]
            for model in (Match, Team, Player)}


def full_payload(stats, fnc_red=False):
    # 完整35121官方详情实际404；此处只验证将来明确提供角色/秒数时的稳定ID升级合同。
    payload = json.loads((Path(__file__).parent / 'fixtures/scoregg_result_66845.json').read_text(encoding='utf-8'))
    data, row = payload['data'], stats['data']['result_list'][0]
    data['resultID'] = '35121'
    for block in ('max_mvp', 'max_beiguo'):
        data[block]['match_id'] = '20839'
    info = data['result_list']
    info.update(teamID_a='102', teamID_b='1', win_teamID='1')
    for color, side in (('red', 'a' if fnc_red else 'b'), ('blue', 'b' if fnc_red else 'a')):
        info[color + '_name'] = row[f'team_{side}_short_name']
        info[color + '_teamID'] = row[f'teamID_{side}']
        info[color + '_result'] = str(int(row[f'teamID_{side}'] == row['win_teamID']))
        for field, mapped in (('kill', 'kills'), ('die', 'deaths'), ('asses', 'assists')):
            info[f'{color}_{field}'] = row[f'{mapped}_{side}']
        for role, record in zip('abcde', row[f'record_list_{side}']):
            prefix = f'{color}_star_{role}_'
            info[prefix + 'playerID'] = record['playerID']
            info[prefix + 'name'] = record['player_nickname']
            for field in ('kills', 'deaths', 'assists', 'mvp', 'beiguo'):
                info[prefix + field] = record[field]
    return payload


def test_real_metadata_preserves_ten_source_ids_and_unknown_roles_time_statistics(db, tmp_path, stats):
    series, raw_dir, archive = ready(db, tmp_path, stats)
    data = normalize_metadata_snapshot(stats, 35121, series.schedule(), archive)
    assert data['matches'][0]['source'] == 'scoregg_metadata'
    assert data['matches'][0]['blue_team_name'] == 'FNC' and data['matches'][0]['red_team_name'] == 'EDG'
    proof = data['matches'][0]['team_name_provenance']
    assert proof['side_basis'] == 'metadata_team_a_b' and proof['detail']['series_id_source'] == 'metadata.data.matchID'
    outcome = ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    assert outcome.status == 'source_incomplete'
    match = db.session.query(Match).one()
    assert match.verified and match.game_time is None and match.win_team_name == 'EDG'
    players = db.session.query(Player).all()
    assert len(players) == 10 and {player.source_player_id for player in players} == {
        '63', '3024', '2463', '602', '600', '132', '2690', '2', '1410', '6'}
    for player in players:
        assert player.position is None and player.game_time is None
        assert all(getattr(player, field) is None for field in ('hero', 'hero_lv', 'kda', 'part', 'atk', 'atk_m',
                                                               'def_', 'def_m', 'money', 'money_M', 'hits', 'adc_m'))
    wunder = next(player for player in players if player.source_player_id == '63')
    assert (wunder.name, wunder.kills, wunder.deaths, wunder.assists) == ('Wunder', 1, 3, 0)
    assert db.session.query(Team).filter_by(team_name='FNC').one().money == 45538
    assert db.session.query(SyncTask).one().status == 'source_incomplete'
    before = business_rows(db)
    assert ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive).status == 'source_incomplete'
    assert business_rows(db) == before
    assert history.coverage_report()['complete_available'] is False


@pytest.mark.parametrize('fnc_red', [False, True])
def test_complete_cdn_upgrades_same_pks_by_source_id_with_real_roles_and_color(db, tmp_path, stats, fnc_red):
    series, _, archive = ready(db, tmp_path, stats)
    ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    player_ids = {player.source_player_id: player.id for player in db.session.query(Player)}
    team_ids = {team.team_name: team.id for team in db.session.query(Team)}
    match_id = db.session.query(Match).one().id
    payload = full_payload(stats, fnc_red)
    assert ingestion.ingest_result(payload, 35121, series.schedule()).status == 'imported'
    match = db.session.query(Match).one()
    assert match.id == match_id and match.source == 'scoregg' and match.game_time == 2509
    assert match.red_team_name == ('FNC' if fnc_red else 'EDG')
    assert {player.source_player_id: player.id for player in db.session.query(Player)} == player_ids
    assert {team.team_name: team.id for team in db.session.query(Team)} == team_ids
    assert all(player.position in 'abcde' for player in db.session.query(Player))
    before = business_rows(db)
    assert ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive).status == 'skipped'
    assert business_rows(db) == before  # 旧 metadata 不反向降级角色、秒数、完整来源。


def test_full_cdn_role_swap_keeps_player_pks_and_does_not_collide_with_old_role_constraint(db, tmp_path, stats):
    series, _, archive = ready(db, tmp_path, stats)
    ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    payload = full_payload(stats)
    ingestion.ingest_result(payload, 35121, series.schedule())
    before = {player.source_player_id: player.id for player in db.session.query(Player)}
    info = payload['data']['result_list']
    for suffix in ('playerID', 'name', 'kills', 'deaths', 'assists', 'mvp', 'beiguo'):
        a, b = f'blue_star_a_{suffix}', f'blue_star_b_{suffix}'
        info[a], info[b] = info[b], info[a]
    assert ingestion.ingest_result(payload, 35121, series.schedule()).status == 'imported'
    assert {player.source_player_id: player.id for player in db.session.query(Player)} == before
    assert db.session.query(Player).filter_by(source_player_id='63').one().position == 'b'


def test_full_refresh_missing_one_known_source_id_preserves_all_existing_business_rows(db, tmp_path, stats):
    series, _, archive = ready(db, tmp_path, stats)
    ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    payload = full_payload(stats)
    assert ingestion.ingest_result(payload, 35121, series.schedule()).status == 'imported'
    before = business_rows(db)
    payload['data']['result_list']['blue_star_a_playerID'] = None
    assert ingestion.ingest_result(payload, 35121, series.schedule()).status == 'failed'
    assert business_rows(db) == before
    assert db.session.query(Player).filter_by(source_player_id='63').one().name == 'Wunder'


def test_first_full_import_missing_one_source_id_remains_compatible(db, tmp_path, stats):
    series, _, _ = ready(db, tmp_path, stats)
    payload = full_payload(stats)
    payload['data']['result_list']['blue_star_a_playerID'] = None
    assert ingestion.ingest_result(payload, 35121, series.schedule()).status == 'imported'
    assert db.session.query(Player).count() == 10
    assert db.session.query(Player).filter_by(name='Wunder').one().source_player_id is None


@pytest.mark.parametrize('bad', ['missing_id', 'different_id', 'duplicate_id'])
def test_unproved_full_roster_identity_does_not_mutate_any_partial_business_row(db, tmp_path, stats, bad):
    series, _, archive = ready(db, tmp_path, stats)
    ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    before = business_rows(db)
    payload = full_payload(stats)
    info = payload['data']['result_list']
    info['blue_star_a_playerID'] = {'missing_id': None, 'different_id': '99999',
                                  'duplicate_id': info['blue_star_b_playerID']}[bad]
    assert ingestion.ingest_result(payload, 35121, series.schedule()).status == 'failed'
    assert business_rows(db) == before


@pytest.mark.parametrize('bad', ['cross_team_source_ids', 'missing_team_ids'])
def test_full_upgrade_must_preserve_each_source_players_known_team_identity(db, tmp_path, stats, bad):
    series, _, archive = ready(db, tmp_path, stats)
    ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    before = business_rows(db)
    payload = full_payload(stats)
    info = payload['data']['result_list']
    schedule = series.schedule()
    if bad == 'cross_team_source_ids':
        for field in ('playerID', 'name'):
            red, blue = f'red_star_a_{field}', f'blue_star_a_{field}'
            info[red], info[blue] = info[blue], info[red]
    else:
        for field in ('red_teamID', 'blue_teamID', 'win_teamID'):
            info.pop(field, None)
        schedule = {key: value for key, value in schedule.items() if key not in ('source_row', 'source_archive')}
    assert ingestion.ingest_result(payload, 35121, schedule).status == 'failed'
    assert business_rows(db) == before


def test_partial_transaction_failure_leaves_zero_business_rows_and_one_failed_attempt(db, tmp_path, stats, monkeypatch):
    series, _, archive = ready(db, tmp_path, stats)
    original = ingestion._upsert_identified_players

    def fail(rows, preserve_nulls):
        original(rows, preserve_nulls)
        raise IntegrityError('test_player_failure', {}, Exception('rollback'))

    monkeypatch.setattr(ingestion, '_upsert_identified_players', fail)
    assert ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive).status == 'failed'
    assert all(db.session.query(model).count() == 0 for model in (Match, Team, Player))
    assert db.session.query(SyncTask).one().failure_count == 1


def test_history_full_detail_404_retains_real_metadata_and_original_detail_body_without_more_requests(db, tmp_path, stats):
    series, raw_dir, _ = ready(db, tmp_path, stats)
    client, transport, _ = source(response(status=404))
    task = db.session.query(SyncTask).one()
    frozen = {path: path.read_bytes() for path in raw_dir.rglob('*') if path.is_file()}
    result = history._fetch_task(client, task, raw_dir, None, NOW)
    assert result['status'] == 'source_incomplete' and result['detail_http_status'] == 404
    assert client.budget.count == 1 and len(transport.calls) == 1
    assert db.session.query(Player).count() == 10 and not (raw_dir / 'scoregg/35121.json').exists()
    assert all(path.read_bytes() == encoded for path, encoded in frozen.items())
    receipt = json.loads(Path(result['source_evidence']).read_bytes())
    assert receipt['detail']['http_status'] == 404
    assert Path(receipt['detail']['response']['raw_file']).read_bytes() == b'<Error>Not Found</Error>'


def test_daily_and_retry_share_genuine_partial_source_without_extra_metadata_call(db, tmp_path, stats):
    series, raw_dir, archive = ready(db, tmp_path, stats)
    schedule = {**series.schedule(), 'metadata_archive': archive}
    run = pipeline.SyncRun(command='daily', status='running')
    db.session.add(run)
    db.session.commit()
    first, _, _ = source(response(status=404))
    outcomes = []
    assert pipeline._fetch_result(first, 35121, schedule, run, raw_dir, outcomes)['status'] == 'source_incomplete'
    ids = {player.source_player_id: player.id for player in db.session.query(Player)}
    retry, _, _ = source(response(status=404))
    # daily 的任务没有持久 source_row；仅从本局已核验 metadata 证明恢复原档，不猜 pub 状态。
    retry_schedule = db.session.query(SyncTask).one().schedule()
    db.session.delete(series)
    db.session.commit()
    assert pipeline._fetch_result(retry, 35121, retry_schedule, run, raw_dir, outcomes)['status'] == 'source_incomplete'
    assert retry.budget.count == 1 and {player.source_player_id: player.id for player in db.session.query(Player)} == ids


def test_actual_retry_with_persisted_series_restores_real_source_row_and_archive(db, tmp_path, stats):
    series, raw_dir, _ = ready(db, tmp_path, stats)
    client, transport, _ = source(response(status=404))
    report, code = pipeline.run_pipeline('retry', client=client, raw_dir=raw_dir,
                                         reports_dir=tmp_path / 'reports', now=NOW)
    assert code == 0 and report['details']['selected_tasks'] == 1
    assert report['details']['outcomes'][0]['status'] == 'source_incomplete'
    assert client.budget.count == 1 and len(transport.calls) == 1
    match = db.session.query(Match).one()
    assert match.series_id == series.series_id and match.date == series.scheduled_at
    assert db.session.query(Player).count() == 10 and db.session.query(SyncTask).one().failure_count == 0


@pytest.mark.parametrize('bad', ['series_id', 'tournament_id', 'scheduled_at', 'archive_sha'])
def test_actual_retry_does_not_replace_known_task_claim_or_trust_bad_series_archive(db, tmp_path, stats, bad):
    series, raw_dir, _ = ready(db, tmp_path, stats)
    task = db.session.query(SyncTask).one()
    if bad == 'scheduled_at':
        task.scheduled_at += timedelta(days=1)
    elif bad == 'archive_sha':
        Path(series.raw_file).write_bytes(b'{}')
    else:
        setattr(task, bad, getattr(task, bad) + 1)
    db.session.commit()
    client, transport, _ = source(response(status=404))
    report, code = pipeline.run_pipeline('retry', client=client, raw_dir=raw_dir,
                                         reports_dir=tmp_path / 'reports', now=NOW)
    assert code == 2 and report['details']['outcomes'][0]['status'] == 'failed'
    assert db.session.query(SyncTask).one().failure_count == 1
    assert all(db.session.query(model).count() == 0 for model in (Match, Team, Player))
    assert client.budget.count == 1 and len(transport.calls) == 1


@pytest.mark.parametrize('change', ['players_change_team', 'teams_exchange_a_b'])
def test_metadata_refresh_checks_player_team_identity_and_allows_actual_a_b_exchange(db, tmp_path, stats, change):
    series, raw_dir, archive = ready(db, tmp_path, stats)
    assert ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive).status == 'source_incomplete'
    before = business_rows(db)
    ids = {player.source_player_id: player.id for player in db.session.query(Player)}
    row = stats['data']['result_list'][0]
    if change == 'players_change_team':
        for field in ('playerID', 'player_nickname'):
            a, b = row['record_list_a'][0], row['record_list_b'][0]
            a[field], b[field] = b[field], a[field]
    else:
        for value in (stats['data'], row):
            for key in list(value):
                other = key[:-2] + '_b' if key.endswith('_a') else key.replace('team_a_', 'team_b_')
                if other != key and other in value:
                    value[key], value[other] = value[other], value[key]
    client, _, _ = source(response(status=404), response(stats))
    with pytest.raises(spider.SourceHTTPError) as caught:
        client.get_result_list(series.series_id)
    _, evidence = spider.metadata_result_list_after_404(client, series.schedule(), raw_dir, caught.value)
    archive = {key: evidence[key] for key in ('raw_file', 'sha256', 'evidence_file')}
    outcome = ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    if change == 'players_change_team':
        assert outcome.status == 'failed'
        assert business_rows(db) == before
    else:
        assert outcome.status == 'source_incomplete'
        assert {player.source_player_id: player.id for player in db.session.query(Player)} == ids
        assert db.session.query(Player).filter_by(source_player_id='63').one().team_name == 'FNC'
        assert db.session.query(Match).one().blue_team_name == 'EDG'


def test_api_exposes_true_a_b_basis_source_ids_and_unknown_minutes_role(db, tmp_path, stats, client):
    series, _, archive = ready(db, tmp_path, stats)
    ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    detail = client.get('/match/api/35121').get_json()
    assert detail['match']['side_basis'] == 'metadata_team_a_b'
    assert detail['match']['blue_team_name'] == 'FNC' and detail['match']['game_time'] is None
    assert len(detail['players']) == 10
    assert all(player['source_player_id'] and player['position'] is None and player['atk_m'] is None
               and player['adc_m'] is None for player in detail['players'])


@pytest.mark.parametrize('bad', ['duplicate_id', 'wrong_team', 'wrong_result', 'missing_name', 'short_roster',
                               'negative_kills', 'fractional_kills', 'team_sum', 'invalid_mvp'])
def test_metadata_roster_or_stat_contradiction_does_not_create_derived_rows(db, tmp_path, stats, bad):
    row = stats['data']['result_list'][0]
    record = row['record_list_a'][0]
    if bad == 'duplicate_id':
        record['playerID'] = row['record_list_b'][0]['playerID']
    elif bad == 'wrong_team':
        record['teamID'] = '1'
    elif bad == 'wrong_result':
        record['resultID'] = '99999'
    elif bad == 'missing_name':
        record['player_nickname'] = ''
    elif bad == 'short_roster':
        row['record_list_a'].pop()
    elif bad == 'negative_kills':
        record['kills'] = '-1'
    elif bad == 'fractional_kills':
        record['kills'] = '0.5'
    elif bad == 'team_sum':
        row['kills_a'] = '99'
    else:
        record['mvp'] = '2'
    series, _, archive = ready(db, tmp_path, stats)
    assert ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive).status == 'failed'
    assert all(db.session.query(model).count() == 0 for model in (Match, Team, Player))
    assert db.session.query(SyncTask).one().failure_count == 1


def test_metadata_advanced_sql_keeps_real_kda_counts_but_has_no_rate_or_role_sample(db, tmp_path, stats):
    from app.services.query_compiler import compile_plan
    from app.services.query_semantics import validate_plan
    from app.services.ai_assistant import execute_readonly_batch

    series, _, archive = ready(db, tmp_path, stats)
    ingestion.ingest_metadata_result(stats, 35121, series.schedule(), archive)
    plan = validate_plan({'type': 'query', 'subject': 'player', 'dimensions': ['player'],
                          'metrics': ['games', 'avg_kills', 'aggregate_kda', 'damage_per_min'],
                          'filters': {'player': ['Wunder'], 'verified_only': True}, 'min_games': 1,
                          'order_by': 'games', 'direction': 'desc', 'limit': 10})
    compiled = compile_plan(plan)
    row = execute_readonly_batch([compiled['statement']])[0][0]
    assert row['games'] == 1 and row['avg_kills'] == 1 and row['aggregate_kda'] == pytest.approx(1 / 3)
    assert row['damage_per_min'] is None and row['damage_per_min_samples'] == 0
    plan['filters']['position'] = ['a']
    assert execute_readonly_batch([compile_plan(plan)['statement']])[0] == []


def test_old_database_startup_requires_explicit_migration_then_nullable_id_roundtrip(tmp_path):
    import sqlite3
    from app import create_app, db
    from scripts.migrate_source_player_id import MigrationError, migrate

    path = tmp_path / 'existing.db'
    with sqlite3.connect(path) as connection:
        connection.executescript('''CREATE TABLE matches(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL UNIQUE);
        CREATE TABLE players(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(match_id),
                             name VARCHAR(100),team_name VARCHAR(100),position VARCHAR(100),
                             UNIQUE(match_id,team_name,position));''')
    config = {'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{path.as_posix()}',
              'DATA_DIR': tmp_path, 'AUTO_CREATE_DB': False, 'AI_API_KEY': ''}
    with pytest.raises(MigrationError, match='migrate_source_player_id'):
        create_app(config)
    with sqlite3.connect(path) as connection:
        assert 'source_player_id' not in {row[1] for row in connection.execute('PRAGMA table_info(players)')}
    assert migrate(path, apply=True)['status'] == 'migrated'
    app = create_app(config)
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
