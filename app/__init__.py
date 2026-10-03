import logging
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, text
from werkzeug.exceptions import BadRequest

from config import BASE_DIR, Config

db = SQLAlchemy()


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None)
    app.static_folder = str(BASE_DIR / "frontend" / "dist")
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    from app.models import match, player, team  # noqa: F401
    from app.models import sync  # noqa: F401
    from app.routes.analytics import analytics_bp
    from app.routes.ai.ai import ai_bp
    from app.routes.hero.hero import hero_bp
    from app.routes.main import main_bp
    from app.routes.match.match import match_bp
    from app.routes.player.player import player_bp
    from app.routes.team.team import team_bp
    from app.routes.sync import sync_bp

    for blueprint in (main_bp, match_bp, player_bp, team_bp, hero_bp, analytics_bp, ai_bp, sync_bp):
        app.register_blueprint(blueprint)

    with app.app_context():
        if db.engine.dialect.name == "sqlite":
            @event.listens_for(db.engine, "connect")
            def configure_sqlite(connection, record):
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
            if app.config["AUTO_CREATE_DB"]:
                db.create_all()

    @app.get("/api/health")
    def health():
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", version="2.0.0")

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path=""):
        if path.startswith(("api/", "player/api", "match/api", "team/api", "hero/api")):
            return jsonify(error="接口不存在"), 404
        static_root = Path(app.static_folder)
        candidate = (static_root / path).resolve()
        if candidate.is_relative_to(static_root.resolve()) and candidate.is_file():
            return send_from_directory(static_root, path, max_age=31536000 if path.startswith("assets/") else 0)
        if path.startswith("assets/"):
            return jsonify(error="资源不存在"), 404
        if (static_root / "index.html").is_file():
            return send_from_directory(static_root, "index.html")
        return jsonify(error="前端尚未构建，请执行 npm run build"), 503

    @app.errorhandler(413)
    def payload_too_large(error):
        return jsonify(error="请求内容过长"), 413

    @app.errorhandler(BadRequest)
    def invalid_request(error):
        return jsonify(error=error.description), 400

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return app
