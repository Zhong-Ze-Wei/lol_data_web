"""API 共用的业务参数校验和数据格式。"""

import re
from datetime import datetime, timedelta

from flask import request
from sqlalchemy import case, func
from werkzeug.exceptions import BadRequest

POSITION_ALIASES = {
    'a': ('a', 'top', '上单'),
    'b': ('b', 'jungle', '打野'),
    'c': ('c', 'mid', 'middle', '中单'),
    'd': ('d', 'adc', 'bottom', 'bot', '射手', 'ADC'),
    'e': ('e', 'support', 'sup', '辅助'),
}
POSITION_LABELS = {'a': '上单', 'b': '打野', 'c': '中单', 'd': '射手', 'e': '辅助'}
POSITION_WEB = {'a': 'top', 'b': 'jungle', 'c': 'mid', 'd': 'adc', 'e': 'support'}
WIN_RESULTS = ('1', '胜', 'win', 'Win', 'WIN')
LOSS_RESULTS = ('0', '负', 'loss', 'Loss', 'LOSS')


def integer_arg(name, default, minimum=1, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    if not re.fullmatch(r'[0-9]+', raw):
        raise BadRequest(f'{name} 必须是整数')
    value = int(raw)
    if value < minimum or (maximum is not None and value > maximum):
        ceiling = f'，最大为 {maximum}' if maximum is not None else ''
        raise BadRequest(f'{name} 最小为 {minimum}{ceiling}')
    return value


def page_args(default_per_page=20):
    return integer_arg('page', 1), integer_arg('per_page', default_per_page, maximum=100)


def pagination_data(pagination):
    return {
        'page': pagination.page, 'per_page': pagination.per_page,
        'total': pagination.total, 'pages': pagination.pages,
        'has_prev': pagination.has_prev, 'has_next': pagination.has_next,
        'prev_num': pagination.prev_num, 'next_num': pagination.next_num,
    }


def canonical_position(value):
    if not value:
        return None
    for key, aliases in POSITION_ALIASES.items():
        if value.lower() in [alias.lower() for alias in aliases]:
            return key
    return None


def position_arg():
    raw = request.args.get('position', '').strip()
    if not raw:
        return None
    position = canonical_position(raw)
    if position is None:
        raise BadRequest('position 必须为 a–e 或 top/jungle/mid/adc/support')
    return position


def position_filter(column, position):
    return column.in_(POSITION_ALIASES[position])


def normalized_position(column):
    return case(*[(column.in_(aliases), key) for key, aliases in POSITION_ALIASES.items()], else_=column)


def _parse_date(value, name, upper=False):
    # 上界采用半开区间：日/月结束日期都包含整日/整月。
    if not re.fullmatch(r'\d{4}-\d{2}(-\d{2})?', value):
        raise BadRequest(f'{name} 必须为 YYYY-MM 或 YYYY-MM-DD')
    pattern = '%Y-%m' if len(value) == 7 else '%Y-%m-%d'
    try:
        parsed = datetime.strptime(value, pattern)
    except ValueError:
        raise BadRequest(f'{name} 不是有效日期') from None
    if upper and len(value) == 7:
        return parsed.replace(year=parsed.year + 1, month=1) if parsed.month == 12 else parsed.replace(month=parsed.month + 1)
    return parsed + timedelta(days=1) if upper else parsed


def date_bounds(start_name='date_from', end_name='date_to'):
    start_raw, end_raw = request.args.get(start_name), request.args.get(end_name)
    start = _parse_date(start_raw, start_name) if start_raw else None
    end = _parse_date(end_raw, end_name, upper=True) if end_raw else None
    if start and end and start >= end:
        raise BadRequest('开始日期不能晚于结束日期')
    return start, end


def filter_dates(query, column, start, end):
    if start:
        query = query.filter(column >= start)
    if end:
        query = query.filter(column < end)
    return query


def rounded(value, digits=2):
    return round(float(value), digits) if value is not None else None


def player_wins(column):
    return func.sum(case((column.in_(WIN_RESULTS), 1), else_=0))


def player_known_results(column):
    return func.sum(case((column.in_(WIN_RESULTS + LOSS_RESULTS), 1), else_=0))


def win_rate(wins, known_results):
    return round(wins / known_results * 100, 2) if known_results else None


def match_data(match):
    return {
        'id': match.id, 'match_id': match.match_id,
        'series_id': match.series_id, 'tournament_id': match.tournament_id,
        'tournament_name': match.tournament_name,
        'date': match.date.strftime('%Y-%m-%d') if match.date and match.date_source == 'schedule' else None,
        'date_source': match.date_source, 'source': match.source, 'verified': match.verified,
        'game_time': match.game_time if match.game_time is not None and match.game_time > 1 else None,
        'red_team_name': match.red_team_name,
        'blue_team_name': match.blue_team_name, 'win_team_name': match.win_team_name,
        'mvp': match.mvp,
    }


def player_data(player, match):
    from app.services.stat_metrics import per_minute_number

    fields = ('name', 'pic', 'hero', 'hero_lv', 'kda', 'kills', 'deaths', 'assists',
              'part', 'atk', 'atk_p', 'atk_m', 'def_', 'def_p', 'def_m', 'adc_m',
              'hits', 'money', 'money_M', 'wp_m', 'team_name', 'position', 'result', 'match_id')
    data = {field: getattr(player, field) for field in fields}
    for key, total in {'atk_m': player.atk, 'def_m': player.def_,
                       'adc_m': player.hits, 'money_M': player.money}.items():
        data[key] = per_minute_number(total, match.game_time)
    data['date'] = match.date.strftime('%Y-%m-%d') if match.date and match.date_source == 'schedule' else None
    data['date_source'] = match.date_source
    return data


def team_data(team):
    fields = ('match_id', 'team_name', 'team_flag', 'result', 'kill', 'death', 'assist',
              'attack', 'money', 'tower', 'small_dargon', 'big_dargon', 'riftHeraldKills',
              'elder', 'void_grub')
    return {field: getattr(team, field) for field in fields}
