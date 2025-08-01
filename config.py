import os

LOG_DIR = 'logs/'
PROXY = None
SPIDER_DEBUG = True

class Config:
    # 数据库配置
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:123456@localhost/lol_data'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # 其他配置项
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
