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
