# routes是路由文件，在里面我们需要注册蓝图
# 如果页面太多会很乱，而且里面存在一些增删改查逻辑。这时候选择分开写会更好
# 在init中注册 在各个页面实现不同功能

# from .match.match import match_bp
# from .player.player import player_bp
# from .hero.hero import hero_bp
# from .main.main import main_bp
#
# def register_routes(app):
#     app.register_blueprint(main_bp, url_prefix='/')
#     app.register_blueprint(match_bp, url_prefix='/match')
#     app.register_blueprint(player_bp, url_prefix='/player')
#     app.register_blueprint(hero_bp, url_prefix='/hero')
#

# 如果这样导入会循环导入 所以在app/__init__.py中去创建就好了