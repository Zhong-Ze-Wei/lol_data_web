"""按完整比赛时长计算逐局分均值，保留未知样本为空。"""

from sqlalchemy import and_, case


def per_minute_value(total_column, duration_column):
    """已知非负总量除以大于 1 秒的比赛时长；1 秒为来源占位。"""
    valid = and_(total_column.is_not(None), total_column >= 0, duration_column > 1)
    return case((valid, total_column * 60.0 / duration_column))


def per_minute_number(total, duration):
    """单条 DTO 使用与 SQL 相同的完整时长和已知总量口径。"""
    if total is None or total < 0 or duration is None or duration <= 1:
        return None
    return total * 60.0 / duration
