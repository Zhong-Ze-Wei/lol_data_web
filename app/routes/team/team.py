from flask import Blueprint, render_template, request, jsonify
from app.models.player import Player
from app.models.match import Match
from app.models.team import Team
from sqlalchemy import func
from sqlalchemy.orm import aliased
from app import db


team_bp = Blueprint('team', __name__, url_prefix='/team')

@team_bp.route('/api/distinct', methods=['GET'])
def distinct_teams():
    """获取不重复的战队名称（分页+模糊搜索）"""
    try:
        page = request.args.get('page', 1, type=int)
        team_name = request.args.get('team_name', '', type=str).strip()

        # 计算每个战队的比赛场数
        team_match_counts = db.session.query(
            Team.team_name,
            func.count(Team.team_name).label('match_count')
        ).filter(Team.team_name.isnot(None))
        
        if team_name:
            team_match_counts = team_match_counts.filter(Team.team_name.ilike(f'%{team_name}%'))
        
        team_match_counts = team_match_counts.group_by(Team.team_name).subquery()
        
        # 查询不重复的战队名，并按比赛场数排序
        query = db.session.query(
            team_match_counts.c.team_name,
            team_match_counts.c.match_count
        ).order_by(team_match_counts.c.match_count.desc())
        
        # 分页
        pagination = query.paginate(page=page, per_page=20, error_out=False)
        
        # 获取所有队伍名称
        team_names = [team.team_name for team in pagination.items]
        
        # 为所有队伍名称查询最新的记录
        latest_teams = db.session.query(Team.team_name, func.max(Team.date).label('max_date')).\
            filter(Team.team_name.in_(team_names)).\
            group_by(Team.team_name).subquery()
        
        # 获取每个队伍最新记录的详细信息
        team_objects = db.session.query(Team.id, Team.team_name).\
            join(latest_teams, 
                 (Team.team_name == latest_teams.c.team_name) & 
                 (Team.date == latest_teams.c.max_date)).all()
        
        # 创建映射字典
        team_dict = {team.team_name: team.id for team in team_objects}

        # 创建team_name到match_count的映射
        match_count_dict = {item.team_name: item.match_count for item in pagination.items}
        
        teams_data = []
        for team_name in team_names:
            teams_data.append({
                'id': team_dict.get(team_name),
                'team_name': team_name,
                'match_count': match_count_dict.get(team_name, 0)
            })

        return jsonify({
            'teams': teams_data,
            'pagination': {
                'page': pagination.page,
                'pages': pagination.pages,
                'has_prev': pagination.has_prev,
                'has_next': pagination.has_next,
                'prev_num': pagination.prev_num,
                'next_num': pagination.next_num
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@team_bp.route('/api/<string:team_name>', methods=['GET'])
def team_detail(team_name):
    """获取特定战队的统计信息及最近一次选手阵容"""
    try:
        from urllib.parse import unquote
        team_name = unquote(team_name)

        team_records = Team.query.filter(Team.team_name == team_name).order_by(Team.date.desc()).all()
        if not team_records:
            return jsonify({'error': '战队不存在'}), 404

        matches_count = len(team_records)
        wins = sum(1 for record in team_records if record.result == 1)
        win_rate = round((wins / matches_count) * 100, 2) if matches_count > 0 else 0

        # 取最近一场比赛的选手信息
        latest_team = team_records[0]
        position_map = {
            'player_a_id': '上单',
            'player_b_id': '打野',
            'player_c_id': '中单',
            'player_d_id': '射手',
            'player_e_id': '辅助'
        }

        players = []
        for field, pos in position_map.items():
            player_name = getattr(latest_team, field)
            if player_name:
                players.append({
                    'player_name': player_name,
                    'position': pos
                })

        team_info = {
            'team_name': team_name,
            'matches_count': matches_count,
            'win_rate': win_rate,
            'players': players
        }
        return jsonify(team_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
