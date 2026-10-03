import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    DATA_DIR = BASE_DIR / "data"
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{(DATA_DIR / 'lol-data.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    AUTO_CREATE_DB = SQLALCHEMY_DATABASE_URI.startswith("sqlite:")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "5100"))
    AI_API_KEY = os.getenv("AI_API_KEY")
    AI_BASE_URL = os.getenv("AI_BASE_URL", "https://aiping.cn/api/v1")
    AI_MODEL = os.getenv("AI_MODEL", "DeepSeek-V4.1-Flash")
    AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "2048"))
    AI_MAX_ROWS = 100
    AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "45"))
    SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "08:00")
    SCHEDULE_TIMEZONE = "Asia/Hong_Kong"
    MAX_CONTENT_LENGTH = 16 * 1024
