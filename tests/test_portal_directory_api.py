from datetime import datetime

import pytest

from app.models import Match, Player


def add_player(db, match_id, name, *, match_date=None, date_source='unknown',
               player_date=None, position='c'):
    db.session.add(Match(match_id=match_id, date=match_date, date_source=date_source,
                         red_team_name='T1', blue_team_name='GEN'))
    db.session.add(Player(match_id=match_id, name=name, team_name='T1',
                          position=position, date=player_date or match_date))


def test_directory_sorts_all_players_before_pagination_and_uses_confirmed_dates(client, db):
    add_player(db, 1, 'Alpha', match_date=datetime(2024, 5, 18), date_source='schedule')
    add_player(db, 2, 'Alpha', match_date=datetime(2026, 10, 4), date_source='updated_at')
    add_player(db, 3, 'Beta', match_date=datetime(2025, 1, 1), date_source='schedule')
    add_player(db, 4, 'Gamma')
    db.session.commit()
    default = client.get('/player/api/list?per_page=1').json
    assert default['pagination']['total'] == 3
    assert default['players'][0]['name'] == 'Alpha'
    assert default['players'][0]['appearance_count'] == 2
    assert default['players'][0]['latest_date'] == '2026-10-04'
    assert default['players'][0]['latest_match_date'] == '2024-05-18'
    recent = client.get('/player/api/list?sort=latest_match_date&per_page=1').json
    assert recent['players'][0]['name'] == 'Beta'
    page_two = client.get('/player/api/list?sort=latest_match_date&per_page=1&page=2').json
    assert page_two['players'][0]['name'] == 'Alpha'
    last = client.get('/player/api/list?sort=latest_match_date&per_page=1&page=3').json
    assert last['players'][0]['name'] == 'Gamma'
    assert last['players'][0]['latest_match_date'] is None
    names = client.get('/player/api/list?sort=name').json['players']
    assert [row['name'] for row in names] == ['Alpha', 'Beta', 'Gamma']


def test_unknown_position_filter_uses_latest_record_and_preserves_known_aliases(client, db):
    add_player(db, 1, 'Null', position=None)
    add_player(db, 2, 'Invalid', position='unrecorded')
    add_player(db, 3, 'Known', position='c')
    add_player(db, 4, 'Alias', position='mid')
    add_player(db, 5, 'Changed', position=None, player_date=datetime(2024, 1, 1))
    add_player(db, 6, 'Changed', position='c', player_date=datetime(2025, 1, 1))
    db.session.commit()
    data = client.get('/player/api/list?position=unknown').json
    assert data['pagination']['total'] == 2
    assert {row['name'] for row in data['players']} == {'Null', 'Invalid'}
    assert len(client.get('/player/api/list').json['players']) == 5


def test_directory_retains_undated_appearances_and_counts_filtered_names(client, db):
    add_player(db, 1, 'Known', match_date=datetime(2025, 1, 1), date_source='schedule')
    db.session.add(Match(match_id=900, date_source='unknown'))
    db.session.add(Player(match_id=900, name='UnknownDate', team_name='Legacy', position=None))
    db.session.commit()
    data = client.get('/player/api/list?sort=latest_match_date&per_page=1&page=2').json
    assert data['pagination']['total'] == 2
    assert data['players'][0]['name'] == 'UnknownDate'
    assert data['players'][0]['appearance_count'] == 1
    assert data['players'][0]['latest_match_date'] is None
    filtered = client.get('/player/api/list?position=unknown&team_name=Legacy').json
    assert filtered['pagination']['total'] == 1
    assert filtered['pagination']['pages'] == 1
    assert filtered['players'][0]['name'] == 'UnknownDate'
    empty = client.get('/player/api/list?team_name=Missing').json
    assert empty['players'] == []
    assert empty['pagination']['total'] == 0
    assert empty['pagination']['pages'] == 0


@pytest.mark.parametrize('sort', ['updated_at', 'win_rate', 'invalid'])
def test_unsupported_directory_sort_is_explicit_400(client, sort):
    response = client.get('/player/api/list', query_string={'sort': sort})
    assert response.status_code == 400
    assert 'sort' in response.json['error']


def test_profile_latest_date_is_from_complete_confirmed_scope_not_current_page(client, db):
    for match_id, played, source in [
        (1, datetime(2024, 5, 18), 'schedule'),
        (2, datetime(2026, 10, 4), 'updated_at'),
        (3, datetime(2025, 1, 1), 'unknown'),
        (4, datetime(2023, 11, 19), 'schedule'),
    ]:
        add_player(db, match_id, 'Faker', match_date=played, date_source=source)
    db.session.commit()
    for page in (1, 2):
        data = client.get(f'/player/api/Faker?page={page}&per_page=1').json
        assert data['latest_match_date'] == '2024-05-18'
        assert data['total'] == 4
        assert len(data['players']) == 1


def test_profile_latest_date_stays_unknown_without_confirmed_schedule(client, db):
    add_player(db, 1, 'Faker', match_date=datetime(2026, 10, 4), date_source='updated_at')
    db.session.commit()
    data = client.get('/player/api/Faker').json
    assert data['latest_match_date'] is None
    assert data['total'] == 1


def test_match_keywords_and_tournaments_filter_before_pagination(client, db):
    for match_id, tournament in [(1, '2024 LCK春季赛'), (2, '2025 LCK春季赛'), (35121, '2022 全球总决赛')]:
        db.session.add(Match(match_id=match_id, tournament_name=tournament,
                             red_team_name='T1', blue_team_name='GEN',
                             date=datetime(2024, 1, 1), date_source='schedule'))
    db.session.commit()
    lck = client.get('/match/api/list?query=lck&per_page=1').json
    assert lck['pagination']['total'] == 2
    assert len(lck['matches']) == 1
    assert client.get('/match/api/list?query=35121').json['matches'][0]['match_id'] == 35121
    assert client.get('/match/api/list?query=t1').json['pagination']['total'] == 3
    narrowed = client.get('/match/api/list?query=GEN&tournament_name=2025%20LCK').json
    assert narrowed['pagination']['total'] == 1
    assert narrowed['matches'][0]['match_id'] == 2
    assert client.get('/match/api/list?query=LCK&team_name1=missing').json['matches'] == []


@pytest.mark.parametrize('keyword', ['9223372036854775808', '18446744073709551615', '9' * 5000],
                         ids=['above_sqlite_integer', 'twenty_digit_text', 'long_text'])
def test_numeric_keyword_outside_match_id_range_remains_a_text_search(client, db, keyword):
    db.session.add(Match(match_id=35121, tournament_name=f'邀请赛 {keyword}',
                         red_team_name='T1', blue_team_name='GEN'))
    db.session.commit()
    response = client.get('/match/api/list', query_string={'query': keyword})
    assert response.status_code == 200
    assert response.json['pagination']['total'] == 1
    assert response.json['matches'][0]['match_id'] == 35121


@pytest.mark.parametrize('filter_name', ['query', 'tournament_name'])
def test_match_search_treats_percent_and_underscore_as_literal_text(client, db, filter_name):
    for match_id, tournament in [(1, '邀请赛%_特别场'), (2, '普通邀请赛')]:
        db.session.add(Match(match_id=match_id, tournament_name=tournament,
                             red_team_name='T1', blue_team_name='GEN'))
    db.session.commit()
    data = client.get('/match/api/list', query_string={filter_name: '%_'}).json
    assert data['pagination']['total'] == 1
    assert data['matches'][0]['match_id'] == 1
