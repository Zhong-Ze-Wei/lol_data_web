import os
import time
import uuid
import logging
from datetime import datetime
from pathlib import Path
from filelock import FileLock, Timeout
import json

# 配置日志记录器
logger = logging.getLogger(__name__)

# 用户交互日志文件路径
USER_INTERACTION_LOG_FILE = "logs/user_interactions.json"

def log_user_interaction(user_name, question, is_relevant, sql_query, sql_success, answer, request_id=None, model_usage=None):
    """
    记录用户交互数据到JSON文件，支持多并发写入
    
    Args:
        user_name: 用户名称
        question: 用户提问
        is_relevant: 是否相关
        sql_query: SQL语句
        sql_success: SQL语句是否成功
        answer: 最终回答
        request_id: 请求ID，如果为None则自动生成
        model_usage: 模型使用信息，包含以下字段:
            - steps: 各步骤信息列表
            - total_time: 总耗时
    """
    try:
        # 创建记录数据
        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "request_id": request_id or str(uuid.uuid4()),
            "user_name": user_name,
            "question": question,
            "is_relevant": is_relevant,
            "sql_query": sql_query,
            "sql_success": sql_success,
            "answer": answer
        }
        
        if model_usage is not None:
            log_entry["model_usage"] = model_usage

        # 确保日志目录存在
        log_file = Path(USER_INTERACTION_LOG_FILE)
        log_file.parent.mkdir(exist_ok=True, parents=True)

        # 使用FileLock获取文件锁，确保并发安全
        lock = FileLock(str(log_file) + ".lock")
        try:
            with lock.acquire(timeout=5):  # 超时5秒
                # 读取现有数据
                data = []
                if log_file.exists():
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                            if content:
                                data = json.loads(content)
                            else:
                                data = []
                    except json.JSONDecodeError:
                        logger.error(f"JSON解析错误，创建新的日志文件")
                        data = []

                # 添加新记录
                data.append(log_entry)

                # 写入更新后的数据
                with open(log_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"用户交互数据已记录到日志文件: {USER_INTERACTION_LOG_FILE}")
        except Timeout:
            logger.error("获取文件锁超时，跳过本次日志记录")
    except Exception as e:
        logger.error(f"记录用户交互数据时出错: {e}")