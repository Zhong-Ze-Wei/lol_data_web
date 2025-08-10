import os
from dotenv import load_dotenv

# 先加载 .env 文件（如果有）
load_dotenv()

LOG_DIR = 'logs/'
PROXY = None
SPIDER_DEBUG = True
LAST_MATCH_ID = 61779  # 上次爬取到的最后一个比赛ID


class Config:
    # 数据库配置
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask密钥
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')

    # DeepSeek API Key
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')