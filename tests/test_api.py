from datetime import datetime

import pytest

from app.models import Match, Player, Team


def add_match(db, match_id, date=None, **fields):
    match = Match(match_id=match_id, date=date, red_team_name='A', blue_team_name='B',
                  win_team_name='A', **fields)
    db.session.add(match)
    db.session.flush()
    return match


@pytest.mark.parametrize('path,key', [
    ('/match/api/list', 'matches'), ('/player/api/list', 'players'),
    ('/team/api/distinct', 'teams'), ('/hero/api/list', 'heroes'),
])
def test_empty_lists_are_successful(client, path, key):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json[key] == []
    assert response.json['pagination']['total'] == 0


@pytest.mark.parametrize('path', [
    '/match/api/list?page=0', '/match/api/list?page=abc',
    '/match/api/list?per_page=101', '/match/api/list?start_date=2024-13',
    '/match/api/list?date_from=2024-05-01&date_to=2024-04-01',
    '/player/api/list?position=banana', '/hero/api/list?page=-1',
])
def test_invalid_filters_return_chinese_400(client, path):
    response = client.get(path)
    assert response.status_code == 400
    assert response.json['error']
    assert any('\u4e00' <= char <= '\u9fff' for char in response.json['error'])


@pytest.mark.parametrize('path', [
    '/match/api/999', '/player/api/unknown', '/team/api/unknown', '/hero/api/unknown',
])
def test_missing_entity_is_404(client, path):
    assert client.get(path).status_code == 404


def test_match_id_is_score_result_id_and_incomplete_history_is_visible(client, db):
    match = add_match(db, 66845, game_time=None, source='legacy', date_source='updated_at')
    db.session.commit()
    response = client.get('/match/api/66845')
    assert response.status_code == 200
    assert response.json['match']['match_id'] == 66845
    assert response.json['match']['id'] == match.id
    assert response.json['match']['game_time'] is None
    assert response.json['match']['verified'] is False
    assert response.json['players'] == []
    assert response.json['red_team'] is None
    assert client.get(f'/match/api/{match.id}').status_code == 404


def test_latest_player_is_stable_for_tied_dates_and_null_dates(client, db):
    date = datetime(2024, 1, 1)
    for match_id, name, team, played in [(1, 'Alice', 'Old', date), (2, 'Alice', 'New', date),
                                        (3, 'Bob', 'B', None)]:
        add_match(db, match_id, date=played)
        db.session.add(Player(match_id=match_id, name=name, team_name=team, position='a', date=played))
    db.session.commit()
    players = client.get('/player/api/list?position=top').json['players']
    assert len(players) == 2
    alice = next(player for player in players if player['name'] == 'Alice')
    assert alice['team_name'] == 'New'
    assert alice['appearance_count'] == 2
    assert client.get('/player/api/list?team_name=Old').json['players'] == []


def test_player_filters_use_latest_role_but_count_complete_history(client, db):
    for match_id, position in [(1, 'a'), (2, 'b')]:
        add_match(db, match_id, date=datetime(2024, 1, match_id))
        db.session.add(Player(match_id=match_id, name='Alice', team_name='A', position=position,
                              date=datetime(2024, 1, match_id)))
    db.session.commit()
    assert client.get('/player/api/list?position=top&player_name=ali').json['players'] == []
    data = client.get('/player/api/list?position=jungle&player_name=ALI').json
    assert data['pagination']['total'] == 1
    assert data['players'][0]['appearance_count'] == 2
    assert data['players'][0]['position'] == 'b'


def test_player_detail_paginates_but_stats_use_full_non_missing_samples(client, db):
    for match_id in range(1, 106):
        add_match(db, match_id)
        db.session.add(Player(match_id=match_id, name='Alice', team_name='A', position='a',
                              kills=2 if match_id == 1 else None, deaths=None, assists=None,
                              money=1200 if match_id == 1 else None,
                              result='1' if match_id == 1 else None, hero='Ahri'))
    db.session.commit()
    data = client.get('/player/api/Alice?per_page=100').json
    assert len(data['players']) == 100
    assert data['pagination']['total'] == 105
    assert data['stats']['totalMatches'] == 105
    assert data['stats']['avgMoney'] == 1200
    assert data['stats']['knownResults'] == 1
    assert data['stats']['winRate'] == 100
    assert data['stats']['avgKDA'] == '2.0/—/—'
    assert data['team_name'] == 'A'
    assert len(client.get('/player/api/Alice?page=2&per_page=100').json['players']) == 5


def test_hero_stats_use_appearances_and_never_player_portrait(client, db):
    add_match(db, 1)
    add_match(db, 2)
    db.session.add_all([
        Player(match_id=1, name='Alice', team_name='A', position='a', hero='Ahri', result='1',
               pic='https://example.invalid/player.jpg', part=52.5, kda=3.2),
        Player(match_id=2, name='Bob', team_name='B', position='a', hero='Ahri', result='0', part=67.5),
    ])
    db.session.commit()
    data = client.get('/hero/api/Ahri').json
    assert data['pic'] is None
    assert data['matches_count'] == 2
    assert data['win_rate'] == 50
    assert data['avg_participation'] == 60
    assert data['avg_kda'] == 3.2
    assert data['position'] == 'top'
    assert client.get('/hero/api/list?position=top').json['heroes'][0]['hero_name'] == 'Ahri'


def test_latest_team_lineup_is_scoped_to_latest_match_and_team(client, db):
    date = datetime(2024, 1, 1)
    for match_id in (1, 2):
        add_match(db, match_id, date=date)
        db.session.add(Team(match_id=match_id, team_name='A', date=date, result=1))
    db.session.add_all([
        Player(match_id=1, name='Old', team_name='A', position='a', date=date),
        Player(match_id=2, name='Current', team_name='A', position='a', date=date),
        Player(match_id=2, name='Opponent', team_name='B', position='a', date=date),
    ])
    db.session.commit()
    detail = client.get('/team/api/A').json
    assert detail['latest_match_id'] == 2
    assert [player['player_name'] for player in detail['players']] == ['Current']
    assert client.get('/team/api/distinct').json['pagination']['total'] == 1


def test_end_month_includes_last_day_without_including_next_month(client, db):
    add_match(db, 1, date=datetime(2024, 2, 29, 23, 59, 59), date_source='schedule')
    add_match(db, 2, date=datetime(2024, 3, 1), date_source='schedule')
    db.session.commit()
    data = client.get('/match/api/list?start_date=2024-02&end_date=2024-02').json
    assert [match['match_id'] for match in data['matches']] == [1]


def test_per_minute_values_are_consistent_across_detail_radar_and_monthly_api(client, db):
    for match_id, duration, damage, taken, money, cs in [
        (1, 600, 1000, 2000, 200, 100),
        (2, 1200, 3000, 6000, 600, 120),
        (3, 1, 9999, 9999, 9999, 999),
        (4, None, 9999, 9999, 9999, 999),
    ]:
        add_match(db, match_id, date=datetime(2024, 1, match_id), date_source='schedule', game_time=duration)
        db.session.add(Player(match_id=match_id, name='Alice', team_name='A', position='a',
                              date=datetime(2022, 9, 27), game_time=9999,
                              atk=damage, def_=taken, money=money, hits=cs,
                              atk_m=damage * 60, def_m=taken * 60, money_M=99999, adc_m=cs * 60))
    db.session.commit()

    detail = client.get('/player/api/Alice').json
    assert detail['stats']['avgAtkM'] == 125
    assert detail['stats']['avgDefM'] == 250
    assert detail['stats']['avgAtkMSamples'] == detail['stats']['avgDefMSamples'] == 2
    assert detail['stats']['totalMatches'] == 4
    records = {row['match_id']: row for row in detail['players']}
    assert records[1]['atk_m'] == 100 and records[1]['money_M'] == 20 and records[1]['adc_m'] == 10
    assert records[2]['atk_m'] == 150 and records[2]['money_M'] == 30 and records[2]['adc_m'] == 6
    assert records[1]['date'] == '2024-01-01' and records[1]['date_source'] == 'schedule'
    assert all(records[match_id]['atk_m'] is None for match_id in (3, 4))
    assert client.get('/match/api/1').json['players'][0]['atk_m'] == 100
    assert client.get('/match/api/3').json['players'][0]['adc_m'] is None

    analytics = client.get('/player/api/Alice/analytics?min_matches=1').json
    assert analytics['metrics']['money_M'] == 25 and analytics['metrics']['adc_m'] == 8
    assert analytics['metric_samples']['money_M'] == analytics['metric_samples']['adc_m'] == 2
    assert analytics['monthly'][0]['money_M'] == 25 and analytics['monthly'][0]['adc_m'] == 8
    assert analytics['monthly'][0]['money_M_samples'] == analytics['monthly'][0]['adc_m_samples'] == 2
    assert analytics['matches_count'] == 4
    # 只变更查询口径，来源原值仍可审计。
    assert db.session.query(Player).filter_by(match_id=1).one().atk_m == 60000


def test_player_record_date_does_not_expose_source_update_as_match_date(client, db):
    add_match(db, 1, date=datetime(2022, 9, 27), date_source='updated_at', game_time=1200)
    db.session.add(Player(match_id=1, name='Alice', team_name='A', position='a', date=datetime(2022, 9, 27)))
    db.session.commit()
    player_record = client.get('/player/api/Alice').json['players'][0]
    match_record = client.get('/match/api/1').json['players'][0]
    assert player_record['date'] is None and match_record['date'] is None
    assert player_record['date_source'] == match_record['date_source'] == 'updated_at'


def test_one_second_placeholder_is_not_a_fastest_match_or_real_display_duration(client, db):
    add_match(db, 1, date=datetime(2024, 1, 1), date_source='schedule', game_time=1)
    add_match(db, 2, date=datetime(2024, 1, 2), date_source='schedule', game_time=1800)
    db.session.commit()
    assert [row['match_id'] for row in client.get('/api/fastest-matches').json['matches']] == [2]
    assert [row['match_id'] for row in client.get('/api/longest-matches').json['matches']] == [2]
    recent = {row['match_id']: row for row in client.get('/api/recent-matches').json['matches']}
    assert recent[1]['game_time'] is None and recent[1]['duration'] == '未知'
    assert client.get('/match/api/1').json['match']['game_time'] is None
    assert db.session.query(Match).filter_by(match_id=1).one().game_time == 1
