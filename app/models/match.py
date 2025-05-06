# 这段代码是 SQLAlchemy 模型定义，在 Flask 中它的作用主要包括 数据库表结构定义 + ORM 映射

from app import db

class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.Integer, primary_key=True)  # 在SQLAlchemy中 主键默认就是id 绷不住了
    match_id = db.Column(db.Integer, unique=True)
    date = db.Column(db.DateTime, nullable=True)  # 比赛日期
    game_time = db.Column(db.Integer, nullable=True)  # 游戏时长
    red_team_name = db.Column(db.String(100), nullable=False)  # 红方队伍名
    blue_team_name = db.Column(db.String(100), nullable=False)  # 蓝方队伍名
    win_team_name = db.Column(db.String(100), nullable=False)
    mvp = db.Column(db.String(100), nullable=True) # mvp选手

    def save(self):
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f"<Match {self.id}>"
