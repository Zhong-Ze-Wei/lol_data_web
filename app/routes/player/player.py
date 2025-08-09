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
    from urllib.parse import unquote
    name = unquote(name)

    # 查询该选手所有比赛记录
    players = Player.query.filter_by(name=name).all()
    if not players:
        return jsonify({'error': '该玩家未收录'}), 404

    # 提取所有比赛ID
    match_ids = list(set(p.match_id for p in players))

    # 查询所有比赛和战队数据
    matches = Match.query.filter(Match.match_id.in_(match_ids)).order_by(Match.date.desc()).all()
    teams = Team.query.filter(Team.match_id.in_(match_ids)).all()

    # 构造比赛列表
    matches_data = [{
        'match_id': m.match_id,
        'date': m.date.strftime('%Y-%m-%d') if m.date else None,
        'game_time': m.game_time,
        'red_team_name': m.red_team_name,
        'blue_team_name': m.blue_team_name,
        'win_team_name': m.win_team_name,
        'mvp': m.mvp
    } for m in matches]

    # 构造战队列表
    teams_data = [{
        'match_id': t.match_id,
        'team_name': t.team_name,
        'team_flag': t.team_flag,
        'result': t.result,
        'kill': t.kill,
        'death': t.death,
        'assist': t.assist,
        'money': t.money,
        'tower': t.tower
    } for t in teams]

    # 构造选手比赛数据列表
    players_data = [{
        'date': p.date.strftime('%Y-%m-%d') if p.date else None,
        'hero': p.hero,
        'hero_lv': p.hero_lv,
        'kda': p.kda,
        'kills': p.kills,
        'deaths': p.deaths,
        'assists': p.assists,
        'part': p.part,
        'atk': p.atk,
        'atk_p': p.atk_p,
        'atk_m': p.atk_m,
        'def_': p.def_,
        'def_p': p.def_p,
        'def_m': p.def_m,
        'hits': p.hits,
        'money': p.money,
        'result': p.result,
        'position': p.position,
        'pic': p.pic,
        'match_id': p.match_id
    } for p in players]

    total_matches = len(players_data)
    if total_matches == 0:
        return jsonify({'error': '该玩家暂无比赛数据'}), 404

    # 计算胜率（result字段为 '1' 表示胜利）
    win_count = sum(1 for p in players_data if p['result'] == '1')
    win_rate = round(win_count / total_matches * 100, 1)

    # 计算KDA均值，防止除零
    avg_kills = round(sum(p['kills'] for p in players_data) / total_matches, 1)
    avg_deaths = round(sum(p['deaths'] for p in players_data) / total_matches, 1)
    avg_assists = round(sum(p['assists'] for p in players_data) / total_matches, 1)

    # 计算经济均值和攻击防御相关均值
    avg_money = round(sum(p['money'] for p in players_data if p['money']) / total_matches, 1)
    avg_atk_m = round(sum(p['atk_m'] for p in players_data if p['atk_m']) / total_matches, 1)
    avg_def_m = round(sum(p['def_m'] for p in players_data if p['def_m']) / total_matches, 1)

    # 统计不同英雄数量（去重）
    hero_pool = len(set(p['hero'] for p in players_data if p['hero']))

    # 选手位置取最常见位置
    from collections import Counter
    positions = [p['position'] for p in players_data if p['position']]
    position_counter = Counter(positions)
    main_position = position_counter.most_common(1)[0][0] if positions else '未知'

    # 选手头像，取最近比赛的
    pic = next((p['pic'] for p in sorted(players_data, key=lambda x: x['date'], reverse=True) if p['pic']), '')

    # 生成选手简介
    bio = (
        f"{name}是一位职业{main_position}选手，职业生涯共参加{total_matches}场比赛，"
        f"胜率{win_rate}%。场均KDA为{avg_kills}/{avg_deaths}/{avg_assists}，"
        f"场均经济{avg_money}，场均输出{avg_atk_m}，场均承伤{avg_def_m}。"
        f"共使用过{hero_pool}个不同英雄。"
    )

    return jsonify({
        'name': name,
        'pic': pic,
        'main_position': main_position,
        'players': players_data,
        'matches': matches_data,
        'teams': teams_data,
        'stats': {
            'totalMatches': total_matches,
            'winRate': win_rate,
            'avgKDA': f"{avg_kills}/{avg_deaths}/{avg_assists}",
            'avgMoney': avg_money,
            'avgAtkM': avg_atk_m,
            'avgDefM': avg_def_m,
            'heroPool': hero_pool,
            'positions': list(position_counter.keys())
        },
        'bio': bio
    })
