from datetime import datetime

from app.models import Match, Player, Team


def seed_dates(db):
    rows = [(1, datetime(2011, 6, 18), 'schedule'),
            (2, datetime(2022, 9, 27), 'updated_at'),
            (3, datetime(2026, 10, 3), None)]
    for match_id, played, source in rows:
        db.session.add(Match(match_id=match_id, date=played, date_source=source,
                             red_team_name='A', blue_team_name='B', win_team_name='A'))
        db.session.flush()
        # 故意保留旧衍生日期，时间分析必须以单局的赛程证据为准。
        db.session.add(Player(match_id=match_id, name='Alice', team_name='A', position='a',
                              date=datetime(2022, 9, 27), result='1', kda=3))
        db.session.add_all([Team(match_id=match_id, team_name='A', date=played, result=1),
                            Team(match_id=match_id, team_name='B', date=played, result=0)])
    db.session.commit()


def test_recent_and_range_do_not_claim_source_updates_as_matches(client, db):
    seed_dates(db)
    assert [row['match_id'] for row in client.get('/api/recent-matches').json['matches']] == [1]
    status = client.get('/api/sync/status').json
    assert status['data_range']['max_date'].startswith('2011-06-18')
    assert status['record_range']['max_date'].startswith('2026-10-03')
    assert status['date_quality']['confirmed'] == 1
    assert status['date_quality']['unconfirmed'] == 2


def test_date_filtered_lists_keep_unmapped_history_visible_only_without_date_filter(client, db):
    seed_dates(db)
    assert client.get('/match/api/list').json['pagination']['total'] == 3
    assert client.get('/match/api/list?date_from=2022-01').json['matches'] == []
    assert client.get('/match/api/list?date_from=2011-01&date_to=2011-12').json['pagination']['total'] == 1


def test_monthly_uses_schedule_date_and_excludes_unconfirmed_dates(client, db):
    seed_dates(db)
    result = client.get('/player/api/Alice/analytics?min_matches=1').json
    assert result['matches_count'] == 3
    assert [(row['month'], row['matches_count']) for row in result['monthly']] == [('2011-06', 1)]
    result = client.get('/player/api/Alice/analytics?date_from=2022-01&min_matches=1').json
    assert result['matches_count'] == 0
    assert result['monthly'] == []


def test_radar_and_team_periods_use_same_confirmed_schedule_scope(client, db):
    seed_dates(db)
    query = '?date_from=2011-01&date_to=2011-12&min_matches=1'
    players = client.get('/api/analytics/players' + query).json
    assert players['players'][0]['matches_count'] == 1
    teams = client.get('/api/analytics/teams?team_names=A,B&date_from=2011-01&date_to=2011-12').json
    assert [row['matches_count'] for row in teams['teams']] == [1, 1]
    assert teams['head_to_head'][0]['matches_count'] == 1
    assert client.get('/api/analytics/teams?team_names=A,B&date_from=2022-01').json['teams'] == []
