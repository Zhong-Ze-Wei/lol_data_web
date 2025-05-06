from flask import Blueprint, render_template, request

from app.models.player import Player
from app.models.match import Match
from app.models.team import Team
from sqlalchemy import func
from sqlalchemy.orm import aliased
from app import db

player_bp = Blueprint("player", __name__, url_prefix='/player')

@player_bp.route('/', methods=['GET'])
def show_players():
    # 获取请求参数
    team_name = request.args.get('team_name')  # 筛选条件：战队名称
    position = request.args.get('position')    # 筛选条件：分路
    page = request.args.get('page', 1, type=int)  # 分页，默认为第1页

    # 子查询：每个选手的最近比赛时间
    latest_game_subquery = (
        db.session.query(
            Player.name.label("name"),
            func.max(Player.date).label("latest_date")
        )
        .group_by(Player.name)
        .subquery()
    )

    # 主查询：获取选手名、头像、最近战队和分路
    PlayerAlias = aliased(Player)
    query = db.session.query(
        PlayerAlias.name,
        PlayerAlias.pic,
        PlayerAlias.team_name,
        PlayerAlias.position,
        latest_game_subquery.c.latest_date  # 添加最新比赛时间
    ).join(
        latest_game_subquery,
        (PlayerAlias.name == latest_game_subquery.c.name) &
        (PlayerAlias.date == latest_game_subquery.c.latest_date)
    )

    # 根据战队名进行筛选
    if team_name:
        query = query.filter(PlayerAlias.team_name.ilike(f'%{team_name}%'))

    # 根据分路进行筛选
    if position:
        query = query.filter(PlayerAlias.position.ilike(f'%{position}%'))

    # 去重，避免重复的选手
    query = query.distinct()

    # 按照最近比赛时间降序排列，优先展示最近打过游戏的人
    query = query.order_by(latest_game_subquery.c.latest_date.desc())

    # 分页
    players = query.paginate(page=page, per_page=24, error_out=False)

    # 返回模板并传递选手数据
    return render_template('player.html', players=players)


@player_bp.route('/<string:name>', methods=['GET'])
def show_player_matches(name):
    # 查找该玩家的所有参赛记录
    players = Player.query.filter_by(name=name).all()
    if not players:
        return "该玩家未收录", 404

    # 提取所有参与过的 match_id
    match_ids = list(set(player.match_id for player in players))

    # 获取所有相关比赛数据
    matches = Match.query.filter(Match.id.in_(match_ids)).order_by(Match.date.desc()).all()

    # 获取所有相关战队数据
    teams = Team.query.filter(Team.match_id.in_(match_ids)).all()

    return render_template(
        'player_detail.html',
        name=name,
        players=players,
        matches=matches,
        teams=teams
    )
