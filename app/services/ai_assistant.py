# app/services/ai_assistant.py
import logging
from sqlalchemy import text
from app import db
from config import Config
from openai import OpenAI  # 用官方openai库调用DeepSeek
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = Config.DEEPSEEK_API_KEY

# 用OpenAI SDK，指定base_url指向DeepSeek服务器
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")



def call_deepseek(prompt: str) -> str:
    is_sql_query = "生成安全的 SQL 查询" in prompt

    if not DEEPSEEK_API_KEY:
        logger.warning("API密钥未设置，使用模拟数据")
        return "SELECT name, kills, deaths FROM players LIMIT 5;" if is_sql_query else "测试回答"

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个数据分析助手。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        content = response.choices[0].message.content
        logger.info("DeepSeek API调用成功")
        return content
    except Exception as e:
        logger.error(f"DeepSeek API调用失败: {e}")
        return "SELECT name, kills, deaths FROM players LIMIT 5;" if is_sql_query else f"调用失败: {e}"

def run_ai_query(user_prompt: str) -> dict:
    logger.info(f"收到AI查询: {user_prompt}")

    # 完整的数据库表结构描述
    schema = """
    数据库表结构：
    1. players表 (存储选手数据):
       - id: INT (主键)
       - date: DATETIME (比赛日期)
       - name: VARCHAR (选手名)
       - pic: VARCHAR (选手图片URL)
       - hero: VARCHAR (英雄名)
       - hero_lv: INT (英雄等级)
       - kda: FLOAT (KDA值)
       - kills: INT (击杀数)
       - deaths: INT (死亡数)
       - assists: INT (助攻数)
       - part: VARCHAR (参团率)
       - atk: INT (攻击次数)
       - atk_p: INT (输出占比)
       - atk_m: INT (分均输出)
       - def_: INT (防御次数)
       - def_p: INT (承伤占比)
       - def_m: INT (分均承伤)
       - adc_m: INT (ADC伤害)
       - money: INT (总经济)
       - money_M: INT (分钟经济)
       - wp_m: INT (分均插眼)
       - hits: INT (补刀数)
       - mvp: INT (是否MVP，1/0)
       - beiguo: VARCHAR (是否背锅)
       - team_name: VARCHAR (所属队伍名)
       - position: VARCHAR (选手位置，abcde分别对应上单打野中单射手辅助)
       - game_time: INT (比赛时间，秒)
       - result: VARCHAR (比赛结果，胜/负)
       - match_id: INT (比赛ID, 关联matches表)

    2. matches表 (存储比赛数据):
       - match_id: INT (主键)
       - date: DATE (比赛日期)
       - blue_team_name: VARCHAR (蓝队名)
       - red_team_name: VARCHAR (红队名)
       - result: VARCHAR (比赛结果)
       - game_time: TIME (比赛时长)

    3. teams表 (存储队伍数据):
       - team_name: VARCHAR (主键)
       - result: VARCHAR (比赛结果)
       - kill: INT (总击杀数)
       - death: INT (总死亡数)
       - assist: INT (总助攻数)

    表关系:
    - players.match_id 关联 matches.match_id
    - players.team_name 关联 teams.team_name
    """

    sql_prompt = f"""
    你是 LOL 数据分析SQL专家，请根据以下数据库结构和要求生成SQL查询。

    # 数据库表结构
    {schema}

    # 查询要求
    请根据问题生成SQL查询:
    "{user_prompt}"

    # 生成规则
    1. 必须使用标准MySQL语法
    2. 表名和字段名必须严格匹配上述结构
    3. 多表查询必须明确JOIN条件
    4. 统计类查询按以下逻辑:
       - 先确定符合条件的选手(如比赛数>10)
       - 然后在这些选手中进行时间范围筛选
       - 最后计算统计指标(KDA等)
    5. 保留关键字处理:
       - 使用反引号(``)包围MySQL保留关键字
       - 特别注意: rank, position, key, order, group等是保留关键字
       - 例如: SELECT COUNT(*) AS `rank` 而不是 SELECT COUNT(*) AS rank

    # 输出要求
    1. 只返回纯SQL语句，不要包含任何前缀(如"sql"、"mysql"等)或标记
    2. 不要包含任何解释、注释或额外文本
    3. 明确列出所需字段，不要用SELECT *
    4. 结果限制100条以内
    5. 禁止生成修改类语句
    6. SQL语句必须直接以SELECT、WITH等关键字开头
    """

    logger.info("正在生成SQL查询...")
    sql_query = call_deepseek(sql_prompt).strip().strip("`")
    logger.info(f"生成的SQL查询: {sql_query}")

    try:
        logger.info("正在执行SQL查询...")
        result = db.session.execute(text(sql_query)).fetchall()
        logger.info(f"SQL查询结果: {result[:5] if result else '空'}")
    except Exception as e:
        error_msg = f"SQL执行错误: {str(e)}"
        logger.error(error_msg)
        db.session.rollback()
        return {
            "question": user_prompt,
            "sql": sql_query,
            "error": error_msg,
            "answer": f"抱歉，执行SQL查询时出现错误: {str(e)}",
            "data": []
        }

    answer_prompt = f"根据以下查询结果，用简洁自然的中文，结合精确精准的数字回答问题：\n问题：{user_prompt}\n结果：{result}"
    logger.info("正在生成回答...")
    final_answer = call_deepseek(answer_prompt)
    logger.info(f"生成的回答: {final_answer[:100]}...")

    # 解析结果为字典列表，兼容SQLAlchemy Row对象
    data_list = []
    if not result:
        logger.warning("SQL查询结果为空")
        data_list = []
    else:
        first_row = result[0]
        try:
            if hasattr(first_row, '_mapping'):
                data_list = [dict(row._mapping) for row in result]
            elif hasattr(result, 'keys'):
                keys = result.keys()
                data_list = [dict(zip(keys, row)) for row in result]
            elif hasattr(first_row, 'keys'):
                data_list = [dict(row) for row in result]
            else:
                # 简单元组情况，按索引返回
                data_list = [dict(enumerate(row)) for row in result]
        except Exception as e:
            logger.error(f"转换查询结果为字典时出错: {e}")
            data_list = [dict(enumerate(row)) for row in result]

    return {
        "question": user_prompt,
        "sql": sql_query,
        "data": data_list,
        "answer": final_answer
    }
