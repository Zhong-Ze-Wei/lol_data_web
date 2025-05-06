# 这段代码是 SQLAlchemy 模型定义，在 Flask 中它的作用主要包括 数据库表结构定义 + ORM 映射

from app import db

class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=True)  # 比赛日期
    team_name = db.Column(db.String(100), nullable=True)  # 队伍名
    team_flag = db.Column(db.String(100), nullable=True)  # 队伍旗帜
    result = db.Column(db.Integer, nullable=True)  # 获胜情况 0 失败，1 胜利
    game_time = db.Column(db.Integer, nullable=True) # 游戏时间
    kill = db.Column(db.Integer, nullable=True)  # 总击杀
    death = db.Column(db.Integer, nullable=True)  # 总死亡
    assist = db.Column(db.Integer, nullable=True)  # 总助攻
    attack = db.Column(db.Integer, nullable=True)  # 总输出
    money = db.Column(db.Float, nullable=True)  # 总经济
    tower = db.Column(db.Integer, nullable=True)  # 战队推塔
    small_dargon  = db.Column(db.Integer, nullable=True)  # 战队小龙
    big_dargon = db.Column(db.Integer, nullable=True)  # 战队大龙
    riftHeraldKills = db.Column(db.Integer, nullable=True)  # 战队峡谷先锋
    elder = db.Column(db.Integer, nullable=True)  # 战队远古巨龙
    void_grub = db.Column(db.Integer, nullable=True)  # 战队巢虫
    firstHerald = db.Column(db.Integer, nullable=True)  # 第一个峡谷先锋
    firstBloodKill = db.Column(db.Integer, nullable=True)  # 一血
    firstTowerKill = db.Column(db.Integer, nullable=True)  # 一塔
    firstDragonKill = db.Column(db.Integer, nullable=True)  # 一龙
    firstBaronKill = db.Column(db.Integer, nullable=True)  # 一巨龙
    first5Kill = db.Column(db.Integer, nullable=True)  # 首次五杀
    first10Kill = db.Column(db.Integer, nullable=True)  # 首次十杀
    mvp = db.Column(db.String(100), nullable=True)  # 获胜方MVP
    beiguo = db.Column(db.String(100), nullable=True)  # 失败方背锅
    #match_id = db.Column(db.Integer, db.ForeignKey('matches.match_id'))  # 定义外键约束
    match_id = db.Column(db.Integer)
    player_a_id = db.Column(db.String(100),  nullable=True)  # 上单
    player_b_id = db.Column(db.String(100),  nullable=True)  # 打野
    player_c_id = db.Column(db.String(100), nullable=True)  # 中单
    player_d_id = db.Column(db.String(100), nullable=True)  # ADC
    player_e_id = db.Column(db.String(100), nullable=True)  # 辅助

    def save(self):
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f"<Team {self.team_name}>"