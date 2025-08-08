from flask import Blueprint, render_template, request, jsonify
from app.models.player import Player
from app.models.match import Match
from app.models.team import Team
from sqlalchemy import func
from sqlalchemy.orm import aliased
from app import db

player_bp = Blueprint("player", __name__, url_prefix='/player')

@player_bp.route('/api/list', methods=['GET'])
def get_players():
    """获取选手列表API"""
    # 获取请求参数
    team_name = request.args.get('team_name')  # 筛选条件：战队名称
    position = request.args.get('position')    # 筛选条件：分路
    page = request.args.get('page', 1, type=int)  # 分页，默认为第1页

    # 子查询：计算每个选手的出场次数和最近比赛时间
    player_stats_subquery = (
        db.session.query(
            Player.name.label("name"),
            func.count(Player.name).label("appearance_count"),
            func.max(Player.date).label("latest_date")
        )
        .group_by(Player.name)
        .subquery()
    )

    # 主查询：获取选手名、头像、最近战队和分路，以及出场次数
    PlayerAlias = aliased(Player)
    query = db.session.query(
        PlayerAlias.name,
        PlayerAlias.pic,
        PlayerAlias.team_name,
        PlayerAlias.position,
        player_stats_subquery.c.latest_date,  # 添加最新比赛时间
        player_stats_subquery.c.appearance_count  # 添加出场次数
    ).join(
        player_stats_subquery,
        (PlayerAlias.name == player_stats_subquery.c.name) &
        (PlayerAlias.date == player_stats_subquery.c.latest_date)
    )

    # 根据战队名进行筛选
    if team_name:
        query = query.filter(PlayerAlias.team_name.ilike(f'%{team_name}%'))

    # 根据分路进行筛选
    if position:
        query = query.filter(PlayerAlias.position.ilike(f'%{position}%'))

    # 去重，避免重复的选手
    query = query.distinct()

    # 按照出场次数降序排列，优先展示出场次数多的选手
    query = query.order_by(player_stats_subquery.c.appearance_count.desc())

    # 分页
    players = query.paginate(page=page, per_page=24, error_out=False)

    # 构造返回数据
    players_data = []
    for player in players.items:
        players_data.append({
            'name': player.name,
            'pic': player.pic,
            'team_name': player.team_name,
            'position': player.position,
            'appearance_count': player.appearance_count,
            'latest_date': player.latest_date.strftime('%Y-%m-%d') if player.latest_date else None
        })

    return jsonify({
        'players': players_data,
        'pagination': {
            'page': players.page,
            'pages': players.pages,
            'has_prev': players.has_prev,
            'has_next': players.has_next,
            'prev_num': players.prev_num,
            'next_num': players.next_num
        }
    })


@player_bp.route('/api/<string:name>', methods=['GET'])
def get_player_matches(name):
    """获取特定选手比赛记录API"""
    # 对URL编码的名称进行解码
    from urllib.parse import unquote
    name = unquote(name)

    # 查找该玩家的所有参赛记录
    players = Player.query.filter_by(name=name).all()
    if not players:
        return jsonify({'error': '该玩家未收录'}), 404

    # 提取所有参与过的 match_id
    match_ids = list(set(player.match_id for player in players))

    # 获取所有相关比赛数据
    matches = Match.query.filter(Match.id.in_(match_ids)).order_by(Match.date.desc()).all()

    # 获取所有相关战队数据
    teams = Team.query.filter(Team.match_id.in_(match_ids)).all()
    
    # 构造返回数据
    players_data = []
    for player in players:
        players_data.append({
            'date': player.date.strftime('%Y-%m-%d') if player.date else None,
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
            'result': player.result,
            'match_id': player.match_id
        })
    
    matches_data = []
    for match in matches:
        matches_data.append({
            'match_id': match.match_id,
            'date': match.date.strftime('%Y-%m-%d') if match.date else None,
            'game_time': match.game_time,
            'red_team_name': match.red_team_name,
            'blue_team_name': match.blue_team_name,
            'win_team_name': match.win_team_name,
            'mvp': match.mvp
        })
    
    teams_data = []
    for team in teams:
        teams_data.append({
            'match_id': team.match_id,
            'team_name': team.team_name,
            'team_flag': team.team_flag,
            'result': team.result,
            'kill': team.kill,
            'death': team.death,
            'assist': team.assist,
            'money': team.money,
            'tower': team.tower
        })

    return jsonify({
        'name': name,
        'players': players_data,
        'matches': matches_data,
        'teams': teams_data
    })
