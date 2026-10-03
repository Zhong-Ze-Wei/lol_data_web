from app import db


class Match(db.Model):
    """一局比赛；match_id 对应 ScoreGG resultID，series_id 对应 BO 系列。"""

    __tablename__ = 'matches'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    series_id = db.Column(db.Integer, nullable=True, index=True)
    tournament_id = db.Column(db.Integer, nullable=True, index=True)
    tournament_name = db.Column(db.String(200), nullable=True)
    date = db.Column(db.DateTime, nullable=True, index=True)
    date_source = db.Column(db.String(30), nullable=True)
    source = db.Column(db.String(30), nullable=False, default='scoregg')
    verified = db.Column(db.Boolean, nullable=False, default=False)
    game_time = db.Column(db.Integer, nullable=True)
    red_team_name = db.Column(db.String(100), nullable=True, index=True)
    blue_team_name = db.Column(db.String(100), nullable=True, index=True)
    win_team_name = db.Column(db.String(100), nullable=True)
    mvp = db.Column(db.String(100), nullable=True)

    def save(self):
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f'<Match {self.match_id}>'
