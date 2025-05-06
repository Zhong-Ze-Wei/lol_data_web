# app/__init__.py
# 整个应用程序的初始化文件
# Flask 项目的核心入口  应用工厂模式（Application Factory Pattern）

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from dotenv import load_dotenv


load_dotenv()

# 初始化 db 和 migrate
db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)

    # 配置加载
    app.config['FLASK_APP'] = os.getenv('FLASK_APP')
    app.config['FLASK_ENV'] = os.getenv('FLASK_ENV')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@"
        f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 初始化数据库与迁移
    db.init_app(app)
    migrate.init_app(app, db)

    # 注册蓝图（延迟导入，避免循环依赖）
    from app.routes.main.main import main_bp
    from app.routes.match.match import match_bp
    from app.routes.player.player import player_bp
    from app.routes.hero.hero import hero_bp

    # 注册蓝图
    app.register_blueprint(main_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(hero_bp)

    return app
