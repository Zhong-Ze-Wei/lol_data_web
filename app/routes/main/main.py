from flask import jsonify
from sqlalchemy import case, func

from app import db
from app.models import Match, Player, Team
from app.routes.common import integer_arg, match_data
from . import main_bp


@main_bp.route('/recent-matches')
def recent_matches():
    recent = Match.query.order_by(Match.date.desc(), Match.id.desc()).limit(10).all()
    matches = []
    for match in recent:
        item = match_data(match)
        item.update(red_team=match.red_team_name, blue_team=match.blue_team_name,
                    winner=match.win_team_name,
                    duration=f'{match.game_time // 60}:{match.game_time % 60:02d}' if match.game_time else '未知')
        matches.append(item)
    return jsonify(matches=matches, status='success')


@main_bp.route('/stats')
def stats():
    counts = db.session.query(
        func.count(Match.id),
        func.sum(case((Match.verified.is_(True), 1), else_=0)),
    ).one()
    return jsonify(stats={
        'matches': counts[0],
        'verified_matches': counts[1] or 0,
        'players': db.session.query(func.count(func.distinct(Player.name))).scalar(),
        'teams': db.session.query(func.count(func.distinct(Team.team_name))).scalar(),
    }, status='success')


@main_bp.route('/top-players')
def top_players():
    count = func.count(Player.id)
    rows = db.session.query(Player.name, count.label('matches_count')).filter(
        Player.name.isnot(None), Player.name != '',
    ).group_by(Player.name).order_by(count.desc(), Player.name).limit(3).all()
    return jsonify(players=[{'name': row.name, 'matches_count': row.matches_count} for row in rows], status='success')


@main_bp.route('/top-teams')
def top_teams():
    minimum = integer_arg('min_matches', 50, maximum=1000000)
    count = func.count(Team.id)
    wins = func.sum(case((Team.result == 1, 1), else_=0))
    known = func.sum(case((Team.result.in_((0, 1)), 1), else_=0))
    rate = wins * 100.0 / func.nullif(known, 0)
    rows = db.session.query(Team.team_name, count.label('matches_count'), rate.label('win_rate')).filter(
        Team.team_name.isnot(None), Team.team_name != '',
    ).group_by(Team.team_name).having(count >= minimum, known > 0).order_by(
        rate.desc(), count.desc(), Team.team_name,
    ).limit(3).all()
    return jsonify(teams=[{'team_name': row.team_name, 'win_rate': round(row.win_rate, 2),
                          'matches_count': row.matches_count} for row in rows], status='success')


def _duration_matches(descending):
    order = Match.game_time.desc() if descending else Match.game_time.asc()
    rows = Match.query.filter(Match.game_time > 0).order_by(order, Match.id.desc()).limit(3).all()
    return jsonify(matches=[match_data(match) for match in rows], status='success')


@main_bp.route('/fastest-matches')
def fastest_matches():
    return _duration_matches(False)


@main_bp.route('/longest-matches')
def longest_matches():
    return _duration_matches(True)


@main_bp.route('/top-kills')
def top_kills():
    rows = Player.query.filter(Player.kills.isnot(None)).order_by(
        Player.kills.desc(), Player.date.desc(), Player.id.desc(),
    ).limit(3).all()
    return jsonify(players=[{'name': player.name, 'hero': player.hero, 'kills': player.kills,
                             'team_name': player.team_name, 'match_id': player.match_id} for player in rows],
                   status='success')
