# 这段代码是 SQLAlchemy 模型定义，在 Flask 中它的作用主要包括 数据库表结构定义 + ORM 映射

from app import db
class Player(db.Model):
    __tablename__ = 'players'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=True)  # 比赛日期
    name = db.Column(db.String(100), nullable=True)  # 选手名
    pic = db.Column(db.String(255), nullable=True)  # 选手图片URL
    hero = db.Column(db.String(255), nullable=True)  # 英雄名
    hero_lv = db.Column(db.Integer, nullable=True)  # 英雄等级
    kda = db.Column(db.Float, nullable=True)  # KDA（转换为浮动数值）
    kills = db.Column(db.Integer, nullable=True)  # 击杀数
    deaths = db.Column(db.Integer, nullable=True)  # 死亡数
    assists = db.Column(db.Integer, nullable=True)  # 助攻数
    part = db.Column(db.String(20), nullable=True)  # 参团率
    atk = db.Column(db.Integer, nullable=True)  # 总输出
    atk_p = db.Column(db.Integer, nullable=True)  # 输出占比
    atk_m = db.Column(db.Integer, nullable=True)  # 分均输出
    def_ = db.Column(db.Integer, nullable=True)  # 承伤总量
    def_p = db.Column(db.Integer, nullable=True)  # 承伤占比
    def_m = db.Column(db.Integer, nullable=True)  # 分均承伤
    adc_m = db.Column(db.Integer, nullable=True)  # 分均补刀
    money = db.Column(db.Integer, nullable=True)  # 总经济
    money_M = db.Column(db.Integer, nullable=True)  # 分钟经济
    wp_m = db.Column(db.Integer, nullable=True)  # 分均插眼（待确认）
    hits = db.Column(db.Integer, nullable=True)  # 补刀数
    mvp = db.Column(db.Integer, nullable=True)  # 是否MVP（1/0）
    beiguo = db.Column(db.String(100), nullable=True)  # 是否背锅（1/0）
    team_name = db.Column(db.String(100), nullable=True)  # 战队名称
    position = db.Column(db.String(100), nullable=True)  # 选手位置（上单/打野等）
    game_time = db.Column(db.Integer, nullable=True)  # 比赛时间（秒）
    result = db.Column(db.String(10), nullable=True)  # 比赛结果（胜/负）
    #match_id = db.Column(db.Integer, db.ForeignKey('matches.match_id'))  # 定义外键约束
    match_id = db.Column(db.Integer)

    def save(self):
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f'<Player {self.name}>'
