import os
from dotenv import load_dotenv

load_dotenv()


LOG_DIR = 'logs/'
PROXY = None
SPIDER_DEBUG = True
LAST_MATCH_ID = 61779  # 上次爬取到的最后一个比赛ID

class Config:
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY') or 'your-secret-key-here'