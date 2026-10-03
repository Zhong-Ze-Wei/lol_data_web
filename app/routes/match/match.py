from flask import Blueprint, jsonify, request

from app.models import Match, Player, Team
from app.routes.common import date_bounds, filter_dates, match_data, page_args, pagination_data, player_data, team_data

match_bp = Blueprint('match', __name__, url_prefix='/match')


@match_bp.route('/api/list')
def get_matches():
    page, per_page = page_args()
    # 同时保留旧前端的月份参数和新分析页的日期参数。
    if 'date_from' in request.args or 'date_to' in request.args:
        start, end = date_bounds()
    else:
        start, end = date_bounds('start_date', 'end_date')
    query = filter_dates(Match.query, Match.date, start, end)
    if start or end:
        query = query.filter(Match.date_source == 'schedule')
    for key in ('team_name1', 'team_name2'):
        name = request.args.get(key, '').strip()
        if name:
            query = query.filter(Match.red_team_name.ilike(f'%{name}%') | Match.blue_team_name.ilike(f'%{name}%'))
    pagination = query.order_by(Match.date.desc(), Match.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )
    matches = []
    for match in pagination.items:
        item = match_data(match)
        item['red_color'] = 'green' if match.win_team_name == match.red_team_name else 'red'
        item['blue_color'] = 'green' if match.win_team_name == match.blue_team_name else 'red'
        matches.append(item)
    return jsonify(matches=matches, pagination=pagination_data(pagination))


@match_bp.route('/api/<int:match_id>')
def get_match(match_id):
    match = Match.query.filter_by(match_id=match_id).first()
    if match is None:
        return jsonify(error='比赛未找到'), 404
    players = Player.query.filter_by(match_id=match_id).order_by(Player.team_name, Player.position).all()
    teams = Team.query.filter_by(match_id=match_id).all()
    by_name = {team.team_name: team_data(team) for team in teams}
    return jsonify(match=match_data(match), players=[player_data(player, match) for player in players],
                   red_team=by_name.get(match.red_team_name), blue_team=by_name.get(match.blue_team_name))
