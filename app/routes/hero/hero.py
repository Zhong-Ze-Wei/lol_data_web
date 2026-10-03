from flask import Blueprint, jsonify, request
from sqlalchemy import func

from app import db
from app.models import Player
from app.routes.common import (POSITION_WEB, canonical_position, normalized_position, page_args, pagination_data, player_known_results,
                               player_wins, position_arg, position_filter, rounded, win_rate)

hero_bp = Blueprint('hero', __name__, url_prefix='/hero')


@hero_bp.route('/api/list')
def hero_list():
    page, per_page = page_args(24)
    position = position_arg()
    count = func.count(Player.id)
    query = db.session.query(Player.hero.label('hero_name'), count.label('matches_count'),
                             player_wins(Player.result).label('wins'),
                             player_known_results(Player.result).label('known')).filter(
        Player.hero.isnot(None), Player.hero != '',
    )
    name = request.args.get('hero_name', '').strip()
    if name:
        query = query.filter(Player.hero.ilike(f'%{name}%'))
    if position:
        query = query.filter(position_filter(Player.position, position))
    pagination = query.group_by(Player.hero).order_by(count.desc(), Player.hero).paginate(
        page=page, per_page=per_page, error_out=False,
    )
    dominant_positions = {}
    names = [row.hero_name for row in pagination.items]
    if position is None and names:
        normalized = normalized_position(Player.position)
        position_counts = db.session.query(Player.hero, normalized.label('position'), count.label('count')).filter(
            Player.hero.in_(names), Player.position.isnot(None),
        ).group_by(Player.hero, normalized).order_by(count.desc(), normalized).all()
        for row in position_counts:
            dominant_positions.setdefault(row.hero, POSITION_WEB.get(row.position))
    return jsonify(heroes=[{'hero_id': row.hero_name, 'hero_name': row.hero_name,
                           'position': POSITION_WEB[position] if position else dominant_positions.get(row.hero_name), 'pic': None,
                           'matches_count': row.matches_count, 'win_rate': win_rate(row.wins, row.known)}
                          for row in pagination.items], pagination=pagination_data(pagination))


@hero_bp.route('/api/<string:hero_name>')
def hero_detail(hero_name):
    fields = {'avg_kda': 'kda', 'avg_kills': 'kills', 'avg_deaths': 'deaths', 'avg_assists': 'assists',
              'avg_participation': 'part', 'avg_gold': 'money', 'avg_damage': 'atk',
              'avg_damage_taken': 'def_', 'avg_cs': 'hits'}
    aggregate = db.session.query(
        func.count(Player.id).label('matches_count'), player_wins(Player.result).label('wins'),
        player_known_results(Player.result).label('known'),
        *[func.avg(getattr(Player, field)).label(key) for key, field in fields.items()],
    ).filter(Player.hero == hero_name).one()
    if aggregate.matches_count == 0:
        return jsonify(error='英雄未收录'), 404
    positions = db.session.query(Player.position, func.count(Player.id).label('count')).filter(
        Player.hero == hero_name, Player.position.isnot(None),
    ).group_by(Player.position).order_by(func.count(Player.id).desc(), Player.position).all()
    main_position = canonical_position(positions[0].position) if positions else None
    data = {key: rounded(getattr(aggregate, key)) for key in fields}
    data.update(hero_id=hero_name, hero_name=hero_name, pic=None,
                position=POSITION_WEB.get(main_position), positions=[row.position for row in positions],
                matches_count=aggregate.matches_count, known_results=aggregate.known,
                win_rate=win_rate(aggregate.wins, aggregate.known))
    return jsonify(data)
