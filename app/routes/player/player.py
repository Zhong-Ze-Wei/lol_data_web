from flask import Blueprint, jsonify, request
from sqlalchemy import case, func
from werkzeug.exceptions import BadRequest

from app import db
from app.models import Match, Player, Team
from app.routes.common import (POSITION_LABELS, canonical_position, match_data, normalized_position, page_args, pagination_data,
                               player_data, player_known_results, player_wins, position_arg, position_filter,
                               rounded, team_data, win_rate)
from app.services.analytics import player_analytics
from app.services.stat_metrics import per_minute_value

player_bp = Blueprint('player', __name__, url_prefix='/player')


@player_bp.route('/api/list')
def get_players():
    page, per_page = page_args(24)
    position_text = request.args.get('position', '').strip()
    position = None if position_text == 'unknown' else position_arg()
    player_name = request.args.get('player_name', '').strip()
    records = Player.query.filter(
        Player.name.isnot(None), Player.name != '',
    )
    if player_name:
        records = records.filter(Player.name.ilike(f'%{player_name}%'))
    counts = records.with_entities(
        Player.name, func.count(Player.id).label('appearance_count'),
    ).group_by(Player.name).subquery()
    # DISTINCT 保留独立的确认赛程扫描，让 SQLite 按 match_id 联接出场，避免按姓名逐行回表。
    confirmed = db.session.query(Match.match_id, Match.date).filter(
        Match.date_source == 'schedule', Match.date.isnot(None),
    ).distinct().subquery()
    dates_query = db.session.query(
        Player.name, func.max(confirmed.c.date).label('latest_match_date'),
    ).select_from(confirmed).join(Player, Player.match_id == confirmed.c.match_id).filter(
        Player.name.isnot(None), Player.name != '',
    )
    if player_name:
        dates_query = dates_query.filter(Player.name.ilike(f'%{player_name}%'))
    dates = dates_query.group_by(Player.name).subquery()
    latest = records.with_entities(
        Player.id.label('id'), Player.name.label('name'),
        func.row_number().over(partition_by=Player.name, order_by=(Player.date.desc(), Player.id.desc())).label('rank'),
    ).subquery()
    latest_records = db.session.query(Player).join(
        latest, Player.id == latest.c.id,
    ).filter(latest.c.rank == 1)
    team_name = request.args.get('team_name', '').strip()
    if team_name:
        latest_records = latest_records.filter(Player.team_name.ilike(f'%{team_name}%'))
    if position:
        latest_records = latest_records.filter(position_filter(Player.position, position))
    elif position_text == 'unknown':
        role = normalized_position(Player.position)
        latest_records = latest_records.filter(role.is_(None) | role.not_in(POSITION_LABELS))
    sort = request.args.get('sort', 'appearance_count')
    orders = {
        'appearance_count': (counts.c.appearance_count.desc(), Player.name),
        'latest_match_date': (dates.c.latest_match_date.desc(), Player.name),
        'name': (Player.name,),
    }
    if sort not in orders:
        raise BadRequest('sort 必须为 appearance_count/latest_match_date/name')
    query = latest_records.add_columns(counts.c.appearance_count, dates.c.latest_match_date).join(
        counts, latest.c.name == counts.c.name,
    ).outerjoin(dates, latest.c.name == dates.c.name)
    pagination = query.order_by(*orders[sort]).paginate(
        page=page, per_page=per_page, error_out=False, count=False,
    )
    pagination.total = latest_records.count()
    players = [{
        'name': player.name, 'pic': player.pic, 'team_name': player.team_name,
        'position': player.position, 'appearance_count': count,
        'latest_date': player.date.strftime('%Y-%m-%d') if player.date else None,
        'latest_match_date': confirmed_date.strftime('%Y-%m-%d') if confirmed_date else None,
    } for player, count, confirmed_date in pagination.items]
    return jsonify(players=players, pagination=pagination_data(pagination))


@player_bp.route('/api/<string:name>')
def get_player_matches(name):
    page, per_page = page_args()
    query = Player.query.filter_by(name=name)
    latest = query.order_by(Player.date.desc(), Player.id.desc()).first()
    if latest is None:
        return jsonify(error='该玩家未收录'), 404
    aggregate = db.session.query(
        func.count(Player.id).label('total'), player_wins(Player.result).label('wins'),
        player_known_results(Player.result).label('known_results'),
        func.avg(Player.kills).label('kills'), func.avg(Player.deaths).label('deaths'),
        func.avg(Player.assists).label('assists'), func.avg(Player.money).label('money'),
        func.avg(per_minute_value(Player.atk, Match.game_time)).label('atk_m'),
        func.avg(per_minute_value(Player.def_, Match.game_time)).label('def_m'),
        func.count(per_minute_value(Player.atk, Match.game_time)).label('atk_m_samples'),
        func.count(per_minute_value(Player.def_, Match.game_time)).label('def_m_samples'),
        func.count(func.distinct(Player.hero)).label('heroes'),
        func.max(case((Match.date_source == 'schedule', Match.date))).label('latest_match_date'),
    ).select_from(Player).join(Match, Match.match_id == Player.match_id).filter(Player.name == name).one()
    positions = db.session.query(Player.position, func.count(Player.id).label('count')).filter(
        Player.name == name, Player.position.isnot(None),
    ).group_by(Player.position).order_by(func.count(Player.id).desc(), Player.position).all()
    main_position = positions[0].position if positions else None
    pagination = query.order_by(Player.date.desc(), Player.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )
    ids = [player.match_id for player in pagination.items]
    matches = Match.query.filter(Match.match_id.in_(ids)).order_by(Match.date.desc(), Match.id.desc()).all() if ids else []
    matches_by_id = {match.match_id: match for match in matches}
    teams = Team.query.filter(Team.match_id.in_(ids)).order_by(Team.match_id.desc(), Team.team_name).all() if ids else []
    rate = win_rate(aggregate.wins, aggregate.known_results)
    averages = [rounded(getattr(aggregate, metric), 1) for metric in ('kills', 'deaths', 'assists')]
    kda_text = '/'.join(str(value) if value is not None else '—' for value in averages)
    position_label = POSITION_LABELS.get(canonical_position(main_position), main_position or '未知位置')
    bio = f'{name} 的主要位置是{position_label}，已收录 {aggregate.total} 场出场记录，使用过 {aggregate.heroes} 个英雄。'
    return jsonify(name=name, pic=latest.pic, team_name=latest.team_name, main_position=main_position,
                   players=[player_data(player, matches_by_id[player.match_id]) for player in pagination.items],
                   matches=[match_data(match) for match in matches], teams=[team_data(team) for team in teams],
                   pagination=pagination_data(pagination), total=aggregate.total,
                   latest_match_date=aggregate.latest_match_date.strftime('%Y-%m-%d') if aggregate.latest_match_date else None,
                   stats={'totalMatches': aggregate.total, 'winRate': rate, 'knownResults': aggregate.known_results,
                          'avgKDA': kda_text, 'avgMoney': rounded(aggregate.money, 1),
                          'avgAtkM': rounded(aggregate.atk_m, 1), 'avgDefM': rounded(aggregate.def_m, 1),
                          'avgAtkMSamples': aggregate.atk_m_samples, 'avgDefMSamples': aggregate.def_m_samples,
                          'heroPool': aggregate.heroes, 'positions': [row.position for row in positions]}, bio=bio)


@player_bp.route('/api/<string:name>/analytics')
def get_player_analytics(name):
    data = player_analytics(name)
    if data is None:
        return jsonify(error='该玩家未收录'), 404
    return jsonify(data)
