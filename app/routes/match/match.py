from flask import Blueprint, render_template, request, jsonify
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from datetime import datetime

match_bp = Blueprint("match", __name__, url_prefix='/match')

# 主体比赛页面，可以筛选某日期内确定战队交手情况
@match_bp.route('/api/list', methods=['GET'])
def get_matches():
    team_name1 = request.args.get('team_name1')
    team_name2 = request.args.get('team_name2')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    page = request.args.get('page', 1, type=int)

    query = Match.query # SQLAlchemy 模型类，对应数据库的matches表

    # 如果提供了战队1名称
    if team_name1:
        query = query.filter(
            (Match.red_team_name.ilike(f'%{team_name1}%')) | (Match.blue_team_name.ilike(f'%{team_name1}%'))
        )

    # 如果提供了战队2名称
    if team_name2:
        query = query.filter(
            (Match.red_team_name.ilike(f'%{team_name2}%')) | (Match.blue_team_name.ilike(f'%{team_name2}%'))
        )

    # ✅ 处理开始时间（YYYY-MM）格式
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m")
            query = query.filter(Match.date >= start_date)
        except ValueError:
            pass  # 可以打印日志或返回错误提示

    # ✅ 处理结束时间（加上一个月的开头）
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m")
            # 设置为下个月的1号，以包含完整的月份
            if end_date.month == 12:
                end_date = end_date.replace(year=end_date.year + 1, month=1)
            else:
                end_date = end_date.replace(month=end_date.month + 1)
            query = query.filter(Match.date < end_date)
        except ValueError:
            pass

    query = query.order_by(Match.date.desc())
    matches = query.paginate(page=page, per_page=20, error_out=False)

    if not matches.items:
        return jsonify({'error': '没有找到符合条件的比赛数据'}), 404

    # 给每个比赛添加胜负颜色
    matches_data = []
    for match in matches.items:
        # 胜利队伍是 red_team_name 的话，红方是绿色，否则是红色
        red_color = 'green' if match.win_team_name == match.red_team_name else 'red'
        blue_color = 'green' if match.win_team_name == match.blue_team_name else 'red'
        
        matches_data.append({
            'match_id': match.match_id,
            'date': match.date.strftime('%Y-%m-%d') if match.date else None,
            'red_team_name': match.red_team_name,
            'blue_team_name': match.blue_team_name,
            'win_team_name': match.win_team_name,
            'red_color': red_color,
            'blue_color': blue_color
        })

    return jsonify({
        'matches': matches_data,
        'pagination': {
            'page': matches.page,
            'pages': matches.pages,
            'has_prev': matches.has_prev,
            'has_next': matches.has_next,
            'prev_num': matches.prev_num,
            'next_num': matches.next_num
        }
    })


@match_bp.route('/api/<int:match_id>', methods=['GET'])
def get_match(match_id):
    # 获取特定比赛数据
    match = Match.query.filter_by(match_id=match_id).first()
    if not match:
        return jsonify({'error': '比赛未找到'}), 404

    # 获取与比赛相关的选手数据
    players = Player.query.filter_by(match_id=match_id).all()
    if not players:
        return jsonify({'error': '没有找到该比赛的选手数据'}), 404

    # 获取与比赛相关的战队数据
    teams = Team.query.filter_by(match_id=match_id).all()
    if not teams:
        return jsonify({'error': '没有找到该比赛的战队数据'}), 404

    red_team = next((team for team in teams if team.team_name == match.red_team_name), None)
    blue_team = next((team for team in teams if team.team_name == match.blue_team_name), None)
    
    # 构造返回数据
    match_data = {
        'match_id': match.match_id,
        'date': match.date.strftime('%Y-%m-%d') if match.date else None,
        'game_time': match.game_time,
        'red_team_name': match.red_team_name,
        'blue_team_name': match.blue_team_name,
        'win_team_name': match.win_team_name,
        'mvp': match.mvp
    }
    
    players_data = []
    for player in players:
        players_data.append({
            'name': player.name,
            'pic': player.pic,
            'hero': player.hero,
            'hero_lv': player.hero_lv,
            'kda': player.kda,
            'kills': player.kills,
            'deaths': player.deaths,
            'assists': player.assists,
            'part': player.part,
            'atk': player.atk,
            'atk_p': player.atk_p,
            'atk_m': player.atk_m,
            'def_': player.def_,
            'def_p': player.def_p,
            'def_m': player.def_m,
            'hits': player.hits,
            'money': player.money,
            'team_name': player.team_name,
            'position': player.position,
            'result': player.result
        })
    
    red_team_data = {
        'team_name': red_team.team_name,
        'team_flag': red_team.team_flag,
        'result': red_team.result,
        'kill': red_team.kill,
        'death': red_team.death,
        'assist': red_team.assist,
        'attack': red_team.attack,
        'money': red_team.money,
        'tower': red_team.tower,
        'small_dargon': red_team.small_dargon,
        'big_dargon': red_team.big_dargon,
        'riftHeraldKills': red_team.riftHeraldKills,
        'elder': red_team.elder
    } if red_team else None
    
    blue_team_data = {
        'team_name': blue_team.team_name,
        'team_flag': blue_team.team_flag,
        'result': blue_team.result,
        'kill': blue_team.kill,
        'death': blue_team.death,
        'assist': blue_team.assist,
        'attack': blue_team.attack,
        'money': blue_team.money,
        'tower': blue_team.tower,
        'small_dargon': blue_team.small_dargon,
        'big_dargon': blue_team.big_dargon,
        'riftHeraldKills': blue_team.riftHeraldKills,
        'elder': blue_team.elder
    } if blue_team else None

    return jsonify({
        'match': match_data,
        'players': players_data,
        'red_team': red_team_data,
        'blue_team': blue_team_data
    })
