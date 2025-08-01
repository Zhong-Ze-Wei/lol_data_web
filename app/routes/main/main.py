from flask import Blueprint, render_template, request, jsonify
from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from sqlalchemy import func, desc, case
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
    return render_template('index.html')

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