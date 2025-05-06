from flask import Blueprint, render_template, request
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from datetime import datetime

match_bp = Blueprint("match", __name__, url_prefix='/match')


# 主体比赛页面，可以筛选某日期内确定战队交手情况
@match_bp.route('/', methods=['GET'])
def show_matches():
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
        return "没有找到符合条件的比赛数据", 404 #返回404页面

    # 给每个比赛添加胜负颜色
    for match in matches.items:
        # 胜利队伍是 red_team_name 的话，红方是绿色，否则是红色
        match.red_color = 'green' if match.win_team_name == match.red_team_name else 'red'
        match.blue_color = 'green' if match.win_team_name == match.blue_team_name else 'red'

    return render_template('match.html', matches=matches)


@match_bp.route('/<int:match_id>', methods=['GET'])
def show_match(match_id):
    # 获取特定比赛数据
    match = Match.query.filter_by(match_id=match_id).first()
    if not match:
        return "比赛未找到", 404

    # 获取与比赛相关的选手数据
    players = Player.query.filter_by(match_id=match_id).all()
    if not players:
        return "没有找到该比赛的选手数据", 404

    # 获取与比赛相关的战队数据
    teams = Team.query.filter_by(match_id=match_id).all()
    if not teams:
        return "没有找到该比赛的战队数据", 404

    red_team = next((team for team in teams if team.team_name == match.red_team_name), None)
    blue_team = next((team for team in teams if team.team_name == match.blue_team_name), None)

    return render_template('match_detail.html', match=match, players=players, red_team=red_team, blue_team=blue_team)
