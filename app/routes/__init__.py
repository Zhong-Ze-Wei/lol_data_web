# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import Config

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    # 注册蓝图
    from app.routes.main.main import main_bp
    from app.routes.player import player_bp
    from app.routes.match import match_bp
    from app.routes.hero import hero_bp
    from app.routes.team import team_bp  # 新增team蓝图

    app.register_blueprint(main_bp, url_prefix='')  # 主页蓝图不需要前缀
    app.register_blueprint(player_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(hero_bp)
    app.register_blueprint(team_bp)  # 注册team蓝图

    # 添加CORS支持，方便前端开发
    from flask_cors import CORS
    CORS(app)

    return app