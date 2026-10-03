"""SQL 汇总比赛表现；雷达只比较同一位置各指标的百分位。"""

from bisect import bisect_left, bisect_right
from itertools import combinations

from flask import request
from sqlalchemy import case, extract, func

from app import db
from app.models import Match, Player, Team
from app.routes.common import (POSITION_ALIASES, POSITION_LABELS, date_bounds, filter_dates, integer_arg,
                               normalized_position, page_args, player_known_results, player_wins,
                               position_arg, position_filter, rounded, win_rate)

AXES = [
    {'key': 'kda', 'label': 'KDA', 'unit': ''},
    {'key': 'part', 'label': '参团率', 'unit': '%'},
    {'key': 'atk_p', 'label': '伤害占比', 'unit': '%'},
    {'key': 'def_p', 'label': '承伤占比', 'unit': '%'},
    {'key': 'money_M', 'label': '分均经济', 'unit': '金币/分钟'},
    {'key': 'adc_m', 'label': '分均补刀', 'unit': '刀/分钟'},
]

DATE_POLICY = '时间筛选和月趋势仅使用已确认赛程日期；来源更新时间与未知日期不参与时间分析。'


def _filters(position, minimum):
    return {'position': position, 'min_matches': minimum,
            'date_from': request.args.get('date_from'), 'date_to': request.args.get('date_to'),
            'date_policy': DATE_POLICY}


def _player_query(start, end, position=None):
    query = filter_dates(Player.query.join(Match, Player.match_id == Match.match_id),
                         Match.date, start, end).filter(Player.name.isnot(None), Player.name != '')
    if start or end:
        query = query.filter(Match.date_source == 'schedule')
    if position:
        query = query.filter(position_filter(Player.position, position) if position in POSITION_ALIASES else Player.position == position)
    return query


def _aggregate_players(start, end, position, minimum, name=None):
    normalized = normalized_position(Player.position)
    count = func.count(Player.id)
    query = _player_query(start, end, position)
    if name is not None:
        query = query.filter(Player.name == name)
    query = query.with_entities(
        Player.name, normalized.label('position'), count.label('matches_count'),
        player_wins(Player.result).label('wins'), player_known_results(Player.result).label('known_results'),
        *[func.avg(getattr(Player, axis['key'])).label(axis['key']) for axis in AXES],
        *[func.count(getattr(Player, axis['key'])).label(f"{axis['key']}_samples") for axis in AXES],
    ).group_by(Player.name, normalized).having(count >= minimum)
    return query.order_by(count.desc(), Player.name, normalized).all()


def _latest_teams(start, end, position, name=None):
    normalized = normalized_position(Player.position)
    query = _player_query(start, end, position)
    if name is not None:
        query = query.filter(Player.name == name)
    latest = query.with_entities(
        Player.name, normalized.label('position'), Player.team_name,
        func.row_number().over(partition_by=(Player.name, normalized),
                               order_by=(Player.date.desc(), Player.id.desc())).label('rank'),
    ).subquery()
    rows = db.session.query(latest.c.name, latest.c.position, latest.c.team_name).filter(latest.c.rank == 1).all()
    return {(row.name, row.position): row.team_name for row in rows}


def _distributions(rows):
    distributions = {}
    for row in rows:
        for axis in AXES:
            value = getattr(row, axis['key'])
            if value is not None:
                distributions.setdefault((row.position, axis['key']), []).append(float(value))
    for values in distributions.values():
        values.sort()
    return distributions


def _percentile(value, values):
    if value is None or not values:
        return None
    if len(values) == 1:
        return 50.0
    low, high = bisect_left(values, value), bisect_right(values, value)
    return round((low + (high - low - 1) / 2) / (len(values) - 1) * 100, 2)


def _player_summary(row, distributions, team_name, eligible=True):
    metrics = {axis['key']: rounded(getattr(row, axis['key'])) for axis in AXES}
    percentiles = {axis['key']: _percentile(getattr(row, axis['key']),
                                          distributions.get((row.position, axis['key']), [])) if eligible else None
                   for axis in AXES}
    return {
        'name': row.name, 'position': row.position, 'position_label': POSITION_LABELS.get(row.position),
        'team_name': team_name, 'matches_count': row.matches_count, 'matches': row.matches_count,
        'wins': row.wins, 'known_results': row.known_results, 'win_rate': win_rate(row.wins, row.known_results),
        'metrics': metrics, 'percentiles': percentiles, 'radar': [percentiles[axis['key']] for axis in AXES],
        'metric_samples': {axis['key']: getattr(row, f"{axis['key']}_samples") for axis in AXES},
    }


def players_analytics():
    position = position_arg()
    minimum = integer_arg('min_matches', 5, maximum=1000000)
    start, end = date_bounds()
    page, per_page = page_args(24)
    # 只加载每名选手/位置的 SQL 聚合结果，百分位的分母始终使用完整同位置样本。
    rows = _aggregate_players(start, end, position, minimum)
    distributions = _distributions(rows)
    teams = _latest_teams(start, end, position)
    offset = (page - 1) * per_page
    total = len(rows)
    pages = (total + per_page - 1) // per_page
    players = [_player_summary(row, distributions, teams.get((row.name, row.position)))
               for row in rows[offset:offset + per_page]]
    cohort_sizes = {}
    for row in rows:
        cohort_sizes[row.position] = cohort_sizes.get(row.position, 0) + 1
    return {'axes': AXES, 'players': players, 'cohort_size': total, 'cohort_sizes': cohort_sizes,
            'filters': _filters(position, minimum),
            'method': '同位置选手指标均值的百分位；并列取排名中点；单人样本为50；缺失指标不计入该轴。',
            'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': pages,
                           'has_prev': page > 1, 'has_next': page < pages,
                           'prev_num': page - 1 if page > 1 else None,
                           'next_num': page + 1 if page < pages else None}}


def _monthly(query):
    year, month = extract('year', Match.date), extract('month', Match.date)
    rows = query.filter(Match.date_source == 'schedule', Match.date.isnot(None)).with_entities(
        year.label('year'), month.label('month'), func.count(Player.id).label('matches_count'),
        player_wins(Player.result).label('wins'), player_known_results(Player.result).label('known'),
        *[func.avg(getattr(Player, axis['key'])).label(axis['key']) for axis in AXES],
    ).group_by(year, month).order_by(year, month).all()
    return [{
        'month': f'{int(row.year):04d}-{int(row.month):02d}', 'matches_count': row.matches_count,
        'win_rate': win_rate(row.wins, row.known),
        **{axis['key']: rounded(getattr(row, axis['key'])) for axis in AXES},
    } for row in rows]


def _heroes(query):
    rows = query.filter(Player.hero.isnot(None), Player.hero != '').with_entities(
        Player.hero, func.count(Player.id).label('matches_count'), player_wins(Player.result).label('wins'),
        player_known_results(Player.result).label('known'), func.avg(Player.kda).label('kda'),
    ).group_by(Player.hero).order_by(func.count(Player.id).desc(), Player.hero).limit(12).all()
    return [{'hero': row.hero, 'hero_name': row.hero, 'matches_count': row.matches_count,
             'win_rate': win_rate(row.wins, row.known), 'kda': rounded(row.kda)} for row in rows]


def player_analytics(name):
    if not db.session.query(Player.id).filter(Player.name == name).first():
        return None
    position = position_arg()
    minimum = integer_arg('min_matches', 5, maximum=1000000)
    start, end = date_bounds()
    target_rows = _aggregate_players(start, end, position, 1, name=name)
    if position is None and target_rows:
        position = target_rows[0].position
    query = _player_query(start, end, position).filter(Player.name == name)
    cohorts = _aggregate_players(start, end, position, minimum)
    target = next((row for row in target_rows if row.position == position), None)
    if target is None:
        summary = {'name': name, 'position': position, 'matches_count': 0, 'metrics': {}, 'radar': [],
                   'percentiles': {}, 'metric_samples': {}, 'win_rate': None}
    else:
        teams = _latest_teams(start, end, position, name=name)
        summary = _player_summary(target, _distributions(cohorts), teams.get((name, position)),
                                  eligible=target.matches_count >= minimum)
    monthly = _monthly(query)
    return {**summary, 'axes': AXES, 'cohort_size': len(cohorts), 'monthly': monthly, 'trends': monthly,
            'heroes': _heroes(query), 'filters': _filters(position, minimum)}


def teams_analytics():
    start, end = date_bounds()
    names = list(dict.fromkeys(name.strip() for name in request.args.get('team_names', '').split(',') if name.strip()))
    if len(names) > 10:
        from werkzeug.exceptions import BadRequest
        raise BadRequest('team_names 最多比较 10 支战队')
    count = func.count(Team.id)
    wins = func.sum(case((Team.result == 1, 1), else_=0))
    known = func.sum(case((Team.result.in_((0, 1)), 1), else_=0))
    fields = {'avg_kills': 'kill', 'avg_deaths': 'death', 'avg_assists': 'assist',
              'avg_money': 'money', 'avg_tower': 'tower', 'avg_game_time': 'game_time'}
    query = filter_dates(Team.query.join(Match, Team.match_id == Match.match_id),
                         Match.date, start, end).filter(Team.team_name.isnot(None), Team.team_name != '')
    if start or end:
        query = query.filter(Match.date_source == 'schedule')
    if names:
        query = query.filter(Team.team_name.in_(names))
    rows = query.with_entities(Team.team_name, count.label('matches_count'), wins.label('wins'), known.label('known'),
                               *[func.avg(getattr(Team, field)).label(key) for key, field in fields.items()]
                               ).group_by(Team.team_name).order_by(count.desc(), Team.team_name).limit(10).all()
    teams = [{'team_name': row.team_name, 'matches_count': row.matches_count, 'wins': row.wins,
              'known_results': row.known, 'win_rate': win_rate(row.wins, row.known),
              **{key: rounded(getattr(row, key)) for key in fields}} for row in rows]
    # 直接交手通过两方名字匹配一局比赛，不把 BO 的多局合为一场。
    pairs = list(combinations(sorted(row.team_name for row in rows), 2))
    head_to_head = []
    if pairs:
        match_query = filter_dates(Match.query, Match.date, start, end)
        if start or end:
            match_query = match_query.filter(Match.date_source == 'schedule')
        matches = match_query.filter(
            Match.red_team_name.in_([row.team_name for row in rows]),
            Match.blue_team_name.in_([row.team_name for row in rows]),
        ).with_entities(Match.red_team_name, Match.blue_team_name, Match.win_team_name,
                        func.count(Match.id).label('count')).group_by(
            Match.red_team_name, Match.blue_team_name, Match.win_team_name,
        ).all()
        for team_a, team_b in pairs:
            selected = [match for match in matches if {match.red_team_name, match.blue_team_name} == {team_a, team_b}]
            total = sum(match.count for match in selected)
            if total:
                a_wins = sum(match.count for match in selected if match.win_team_name == team_a)
                b_wins = sum(match.count for match in selected if match.win_team_name == team_b)
                head_to_head.append({'team_a': team_a, 'team_b': team_b, 'matches_count': total,
                                     'team_a_wins': a_wins, 'team_b_wins': b_wins,
                                     'unknown_results': total - a_wins - b_wins})
    return {'teams': teams, 'head_to_head': head_to_head,
            'filters': {'team_names': names, 'date_from': request.args.get('date_from'),
                        'date_to': request.args.get('date_to'), 'date_policy': DATE_POLICY}}
