# app/__init__.py
from flask import Flask, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv

# 固定加载项目根目录的 .env
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"))

from config import Config

db = SQLAlchemy()

def create_app():
    app = Flask(__name__, static_folder="../frontend/dist")
    app.config.from_object(Config)
    db.init_app(app)

    # 注册蓝图
    from app.routes.main import main_bp, root_bp
    from app.routes.player import player_bp
    from app.routes.match import match_bp
    from app.routes.hero import hero_bp
    from app.routes.team import team_bp
    from app.routes.ai import ai_bp

    app.register_blueprint(root_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(hero_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(ai_bp)

    # 静态文件处理
    @app.route('/<path:filename>')
    def static_files(filename):
        file_path = os.path.join(app.static_folder, filename)
        if os.path.exists(file_path):
            return send_from_directory(app.static_folder, filename)
        return send_from_directory(app.static_folder, 'index.html')

    @app.route('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    # 跨域
    from flask_cors import CORS
    CORS(app)

    return app
