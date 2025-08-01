
from flask import Blueprint

# 创建蓝图
main_bp = Blueprint('main', __name__, url_prefix='/api')
root_bp = Blueprint('root', __name__)

# 在创建蓝图之后导入路由定义，避免循环导入
from .main import *

# 确保蓝图被正确导出
__all__ = ['main_bp', 'root_bp']
