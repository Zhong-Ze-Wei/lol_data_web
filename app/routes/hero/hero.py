from flask import Blueprint, render_template

hero_bp = Blueprint("hero", __name__, url_prefix="/hero")

@hero_bp.route("/", methods=["GET"])
def hero_list():
    # 后期替换为真实逻辑
    return "这是英雄列表页面（待开发）"
