from flask import Blueprint, jsonify

from app.services.analytics import players_analytics, teams_analytics

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


@analytics_bp.route('/players')
def get_players_analytics():
    return jsonify(players_analytics())


@analytics_bp.route('/teams')
def get_teams_analytics():
    return jsonify(teams_analytics())
