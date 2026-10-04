from app import db


class Player(db.Model):
    """选手的一次出场；百分比以 0–100 保存，分均指标保留小数。"""

    __tablename__ = 'players'
    __table_args__ = (
        db.UniqueConstraint('match_id', 'team_name', 'position', name='uq_player_match_team_position'),
        db.Index('uq_player_match_source_player', 'match_id', 'source_player_id', unique=True),
        db.Index('ix_player_name_date_id', 'name', 'date', 'id'),
        db.Index('ix_player_position_date', 'position', 'date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=True, index=True)
    name = db.Column(db.String(100), nullable=True, index=True)
    source_player_id = db.Column(db.String(100), nullable=True)
    pic = db.Column(db.String(255), nullable=True)
    hero = db.Column(db.String(255), nullable=True, index=True)
    hero_lv = db.Column(db.Integer, nullable=True)
    kda = db.Column(db.Float, nullable=True)
    kills = db.Column(db.Integer, nullable=True)
    deaths = db.Column(db.Integer, nullable=True)
    assists = db.Column(db.Integer, nullable=True)
    part = db.Column(db.Float, nullable=True)
    atk = db.Column(db.Integer, nullable=True)
    atk_p = db.Column(db.Float, nullable=True)
    atk_m = db.Column(db.Float, nullable=True)
    def_ = db.Column(db.Integer, nullable=True)
    def_p = db.Column(db.Float, nullable=True)
    def_m = db.Column(db.Float, nullable=True)
    adc_m = db.Column(db.Float, nullable=True)
    money = db.Column(db.Integer, nullable=True)
    money_M = db.Column(db.Float, nullable=True)
    wp_m = db.Column(db.Float, nullable=True)
    hits = db.Column(db.Integer, nullable=True)
    mvp = db.Column(db.Integer, nullable=True)
    beiguo = db.Column(db.String(100), nullable=True)
    team_name = db.Column(db.String(100), nullable=True, index=True)
    position = db.Column(db.String(100), nullable=True, index=True)
    game_time = db.Column(db.Integer, nullable=True)
    result = db.Column(db.String(10), nullable=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.match_id'), nullable=False, index=True)

    def save(self):
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f'<Player {self.name} in {self.match_id}>'
