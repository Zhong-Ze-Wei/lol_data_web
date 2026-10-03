from datetime import datetime

import pytest

from app.models import Match, Player, Team


def seed_cohort(db):
    for match_id in range(1, 6):
        date = datetime(2024, 1 if match_id <= 3 else 2, match_id)
        db.session.add(Match(match_id=match_id, date=date, date_source='schedule', red_team_name='A', blue_team_name='B',
                             win_team_name='A' if match_id <= 3 else 'B'))
        db.session.flush()
        db.session.add_all([
            Player(match_id=match_id, date=date, name='Alice', team_name='A', position='a',
                   kda=2, part=50.5, atk_p=20, def_p=None, money_M=400.5, adc_m=7.25,
                   result='1' if match_id <= 3 else '0', hero='Ahri'),
            Player(match_id=match_id, date=date, name='Bob', team_name='B', position='a',
                   kda=4, part=70.5, atk_p=40, def_p=30, money_M=400.5, adc_m=9.25,
                   result='0' if match_id <= 3 else '1', hero='Aatrox'),
            Player(match_id=match_id, date=date, name='Mid', team_name='A', position='c',
                   kda=99, part=99, atk_p=99, def_p=99, money_M=999, adc_m=99, result='1'),
            Team(match_id=match_id, date=date, team_name='A', result=1 if match_id <= 3 else 0, kill=10),
            Team(match_id=match_id, date=date, team_name='B', result=0 if match_id <= 3 else 1, kill=5),
        ])
    db.session.commit()


def test_radar_is_position_percentile_and_preserves_missing_metrics(client, db):
    seed_cohort(db)
    data = client.get('/api/analytics/players?position=top').json
    assert data['cohort_size'] == 2
    assert [axis['key'] for axis in data['axes']] == ['kda', 'part', 'atk_p', 'def_p', 'money_M', 'adc_m']
    alice, bob = data['players']
    assert alice['name'] == 'Alice'
    assert alice['metrics']['part'] == 50.5
    assert alice['metrics']['adc_m'] == 7.25
    assert alice['radar'] == [0.0, 0.0, 0.0, None, 50.0, 0.0]
    assert bob['radar'] == [100.0, 100.0, 100.0, 50.0, 50.0, 100.0]
    assert alice['metric_samples']['def_p'] == 0
    assert bob['metric_samples']['def_p'] == 5
    assert alice['win_rate'] == 60
    assert 'score' not in alice


def test_percentiles_do_not_change_with_pagination(client, db):
    seed_cohort(db)
    first = client.get('/api/analytics/players?position=a&per_page=1').json
    second = client.get('/api/analytics/players?position=a&per_page=1&page=2').json
    assert first['pagination']['total'] == 2
    assert first['players'][0]['radar'][0] == 0
    assert second['players'][0]['radar'][0] == 100


def test_date_filter_and_minimum_apply_before_cohort_ranking(client, db):
    seed_cohort(db)
    data = client.get('/api/analytics/players?position=a&date_from=2024-02&date_to=2024-02&min_matches=3').json
    assert data['players'] == []
    data = client.get('/api/analytics/players?position=a&date_from=2024-02&date_to=2024-02&min_matches=2').json
    assert data['players'][0]['matches_count'] == 2
    assert data['players'][0]['win_rate'] == 0


def test_player_analytics_monthly_and_heroes_share_same_scope(client, db):
    seed_cohort(db)
    data = client.get('/player/api/Alice/analytics').json
    assert data['position'] == 'a'
    assert data['radar'][0] == 0
    assert data['team_name'] == 'A'
    assert [(row['month'], row['matches_count'], row['win_rate']) for row in data['monthly']] == [
        ('2024-01', 3, 100), ('2024-02', 2, 0),
    ]
    assert data['heroes'][0]['hero_name'] == 'Ahri'
    assert data['heroes'][0]['matches_count'] == 5
    limited = client.get('/player/api/Alice/analytics?date_from=2024-02&min_matches=5').json
    assert limited['matches_count'] == 2
    assert limited['radar'] == [None] * 6
    assert len(limited['monthly']) == 1
    assert limited['heroes'][0]['matches_count'] == 2


def test_player_with_no_records_in_range_remains_a_valid_entity(client, db):
    seed_cohort(db)
    response = client.get('/player/api/Alice/analytics?date_from=2026-01')
    assert response.status_code == 200
    assert response.json['matches_count'] == 0
    assert response.json['monthly'] == []
    assert client.get('/player/api/unknown/analytics').status_code == 404


def test_team_comparison_and_head_to_head_count_games(client, db):
    seed_cohort(db)
    data = client.get('/api/analytics/teams?team_names=A,B').json
    assert data['teams'][0]['matches_count'] == 5
    assert data['teams'][0]['win_rate'] == 60
    assert data['teams'][0]['avg_money'] is None
    assert data['head_to_head'] == [
        {'team_a': 'A', 'team_b': 'B', 'matches_count': 5,
         'team_a_wins': 3, 'team_b_wins': 2, 'unknown_results': 0},
    ]
    assert client.get('/api/analytics/teams?team_names=unknown').json['teams'] == []


@pytest.mark.parametrize('path', [
    '/api/analytics/players?min_matches=0', '/api/analytics/players?position=invalid',
    '/api/analytics/players?date_to=2024-02-30',
    '/api/analytics/teams?team_names=a,b,c,d,e,f,g,h,i,j,k',
])
def test_analytics_reject_invalid_parameters(client, path):
    assert client.get(path).status_code == 400
