from flask import Blueprint, jsonify, request
from sqlalchemy import case, func

from app import db
from app.models import Match, Player, Team
from app.routes.common import POSITION_LABELS, canonical_position, match_data, page_args, pagination_data, team_data, win_rate

team_bp = Blueprint('team', __name__, url_prefix='/team')


@team_bp.route('/api/distinct')
def distinct_teams():
    page, per_page = page_args()
    count = func.count(Team.id)
    counts = db.session.query(Team.team_name, count.label('match_count')).filter(
        Team.team_name.isnot(None), Team.team_name != '',
    ).group_by(Team.team_name).subquery()
    latest = db.session.query(
        Team.id.label('id'), Team.team_name.label('team_name'),
        func.row_number().over(partition_by=Team.team_name, order_by=(Team.date.desc(), Team.id.desc())).label('rank'),
    ).subquery()
    query = db.session.query(Team, counts.c.match_count).join(latest, latest.c.id == Team.id).join(
        counts, counts.c.team_name == latest.c.team_name,
    ).filter(latest.c.rank == 1)
    name = request.args.get('team_name', '').strip()
    if name:
        query = query.filter(Team.team_name.ilike(f'%{name}%'))
    pagination = query.order_by(counts.c.match_count.desc(), Team.team_name).paginate(
        page=page, per_page=per_page, error_out=False,
    )
    return jsonify(teams=[{'id': team.id, 'team_name': team.team_name, 'team_flag': team.team_flag,
                          'match_count': matches} for team, matches in pagination.items],
                   pagination=pagination_data(pagination))


@team_bp.route('/api/<string:team_name>')
def team_detail(team_name):
    page, per_page = page_args()
    query = Team.query.filter_by(team_name=team_name)
    latest = query.order_by(Team.date.desc(), Team.id.desc()).first()
    if latest is None:
        return jsonify(error='战队不存在'), 404
    count, wins, known = db.session.query(
        func.count(Team.id), func.sum(case((Team.result == 1, 1), else_=0)),
        func.sum(case((Team.result.in_((0, 1)), 1), else_=0)),
    ).filter(Team.team_name == team_name).one()
    lineup = Player.query.filter_by(match_id=latest.match_id, team_name=team_name).order_by(Player.position).all()
    if lineup:
        players = [{'player_name': player.name, 'position': POSITION_LABELS.get(canonical_position(player.position), player.position),
                    'position_code': canonical_position(player.position), 'pic': player.pic} for player in lineup]
    else:
        players = [{'player_name': getattr(latest, f'player_{position}_id'), 'position': label, 'position_code': position}
                   for position, label in POSITION_LABELS.items() if getattr(latest, f'player_{position}_id')]
    pagination = query.order_by(Team.date.desc(), Team.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    ids = [team.match_id for team in pagination.items]
    matches = Match.query.filter(Match.match_id.in_(ids)).order_by(Match.date.desc(), Match.id.desc()).all() if ids else []
    return jsonify(team_name=team_name, team_flag=latest.team_flag, matches_count=count,
                   wins=wins, known_results=known, win_rate=win_rate(wins, known), players=players,
                   latest_match_id=latest.match_id, records=[team_data(team) for team in pagination.items],
                   matches=[match_data(match) for match in matches], pagination=pagination_data(pagination), total=count)
