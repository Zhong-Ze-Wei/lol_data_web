from flask import Blueprint, render_template, request, jsonify
from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from sqlalchemy import func, desc, case, asc
import openai
import os
from dotenv import load_dotenv
from datetime import datetime

# 加载 .env 文件中的环境变量
load_dotenv()
openai.api_key = os.getenv('DEEPSEEK_API_KEY')

from . import main_bp
from . import root_bp

@root_bp.route('/')
def home():
    return "请通过 Nginx 访问前端页面"

@main_bp.route('/recent-matches')
def recent_matches():
    try:
        recent = db.session.query(Match).order_by(desc(Match.date)).limit(10).all()
        matches_data = [{
            'id': m.id,
            'red_team': m.red_team_name,
            'blue_team': m.blue_team_name,
            'winner': m.win_team_name,
            'duration': f"{m.game_time // 60}:{m.game_time % 60:02d}" if m.game_time else "未知"
        } for m in recent]
        return jsonify({'matches': matches_data, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@main_bp.route('/stats')
def stats():
    try:
        match_count = db.session.query(Match).count()
        # 修改职业选手数量统计逻辑，使用类似战队数量的去重统计方式
        player_count = db.session.query(func.count(func.distinct(Player.name))).scalar()
        # 修正战队数量统计逻辑，使用正确的模型字段
        team_count = db.session.query(func.count(func.distinct(Team.team_name))).scalar()
        
        return jsonify({
            'stats': {
                'matches': match_count,
                'players': player_count,
                'teams': team_count
            },
            'status': 'success'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@main_bp.route('/top-players')
def top_players():
    try:
        # 获取参赛场次最多的选手TOP3
        top_players = db.session.query(
            Player.name,
            func.count(Player.match_id).label('matches_count')
        ).group_by(Player.name).order_by(desc('matches_count')).limit(3).all()
        
        players_data = [{
            'name': player.name,
            'matches_count': player.matches_count
        } for player in top_players]
        
        return jsonify({'players': players_data, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@main_bp.route('/top-teams')
def top_teams():
    try:
        # 获取胜率最高的战队TOP3（排除少于50场数据的战队）
        team_stats = db.session.query(
            Team.team_name,
            func.count(Team.id).label('total_matches'),
            func.sum(case((Team.result == 1, 1), else_=0)).label('wins')
        ).group_by(Team.team_name).having(func.count(Team.id) >= 50).all()
        
        teams_with_win_rate = []
        for team in team_stats:
            win_rate = (team.wins / team.total_matches) * 100
            teams_with_win_rate.append({
                'team_name': team.team_name,
                'win_rate': round(win_rate, 2)
            })
        
        # 按胜率排序并取前3名
        top_teams = sorted(teams_with_win_rate, key=lambda x: x['win_rate'], reverse=True)[:3]
        
        return jsonify({'teams': top_teams, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@main_bp.route('/fastest-matches')
def fastest_matches():
    try:
        # 获取结束最快的战斗TOP3
        fastest = db.session.query(Match).filter(Match.game_time.isnot(None)).order_by(asc(Match.game_time)).limit(3).all()
        
        matches_data = [{
            'id': match.id,
            'red_team_name': match.red_team_name,
            'blue_team_name': match.blue_team_name,
            'game_time': match.game_time
        } for match in fastest]
        
        return jsonify({'matches': matches_data, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# 添加最长比赛时间的TOP3
@main_bp.route('/longest-matches')
def longest_matches():
    try:
        # 获取结束最慢的战斗TOP3
        longest = db.session.query(Match).filter(Match.game_time.isnot(None)).order_by(desc(Match.game_time)).limit(3).all()
        
        matches_data = [{
            'id': match.id,
            'red_team_name': match.red_team_name,
            'blue_team_name': match.blue_team_name,
            'game_time': match.game_time
        } for match in longest]
        
        return jsonify({'matches': matches_data, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# 添加单场击杀最多的三名选手
@main_bp.route('/top-kills')
def top_kills():
    try:
        # 获取单场击杀数最高的TOP3选手
        top_killers = db.session.query(Player).filter(Player.kills.isnot(None)).order_by(desc(Player.kills)).limit(3).all()
        
        players_data = [{
            'name': player.name,
            'hero': player.hero,
            'kills': player.kills,
            'team_name': player.team_name
        } for player in top_killers]
        
        return jsonify({'players': players_data, 'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
