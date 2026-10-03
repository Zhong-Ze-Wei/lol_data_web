"""首页四项全库统计；调用方决定读取事务边界。"""

from sqlalchemy import case, func

from app import db
from app.models import Match, Player, Team


def overview_stats():
    counts = db.session.query(
        func.count(Match.id),
        func.sum(case((Match.verified.is_(True), 1), else_=0)),
    ).one()
    return {
        'matches': counts[0],
        'verified_matches': counts[1] or 0,
        'players': db.session.query(func.count(func.distinct(Player.name))).scalar(),
        'teams': db.session.query(func.count(func.distinct(Team.team_name))).scalar(),
    }
