# 与scripts/import_data.py高度相关，结合models

import json
import requests
from app.models.match import Match
from app.models.player import Player
from datetime import datetime

def get_match_data(match_id):
    try:
        url = f'https://img.scoregg.com/match/result/{match_id}.json?_=1660730052072'
        res = requests.get(url)
        res.raise_for_status()

        # 这里加载json文件，其中data部分主体非常大
        raw_data = json.loads(res.text)
        info0 = raw_data.get('data', {}) #原始json文件中data部分
        info = info0.get('result_list') # 主体数据
        dragon_list = info0.get('dragon_list', {}) #部分额外数据

        # 不在 result_list 的全局数据,则直接结束
        date_str = info0.get('updated_at', None)
        try:
            date = datetime.strptime(date_str, "%Y%m%d%H%M%S") if date_str else None
        except ValueError:
            date = None
        mvp = info0.get('max_mvp', {}).get('nickname', None)
        beiguo = info0.get('max_beiguo', {}).get('nickname', None)

        # 防止 result_list 是 None
        if not isinstance(info, dict):
            print(f"跳过比赛 {match_id}，info 类型异常: {type(info)}")
            return None

        # 如果战队名包含中文，跳过比赛
        red_team = info.get('red_name', None)
        blue_team = info.get('blue_name', None)
        if is_chinese(red_team or "") or is_chinese(blue_team or ""):
            print(f"跳过比赛 {match_id}，因为战队名包含中文。")
            return None
        # 游戏时间（秒）
        duration = int(info.get('game_time_m', 0) or 0) * 60 + int(info.get('game_time_s', 0) or 0)
        teams = ['red', 'blue']

        # 爬取的三个主体：

        #比赛数据 ，包括比赛ID，比赛日期，比赛时长，红蓝方队名
        matches_data = []

        match_data= {
            'match_id': match_id,  # 比赛ID
            'date': date,  # 比赛日期
            'game_time':duration,
            'red_team_name':red_team,
            'blue_team_name': blue_team,
            'mvp':mvp,
            'win_team_name':red_team if info.get('red_result') == "1" else blue_team
        }
        matches_data.append(match_data)

        # 战队数据，这里遍历红蓝方

        teams_data=[]
        for team in teams:
            result = int(info.get(f'{team}_result', 0) or 0)
            # 获取该队的首杀数据（注意用 team 变量，不是字符串 '{team}'）
            team_dragon = dragon_list.get(team, {})
            team_data = {
                'match_id': match_id,  # 比赛ID
                'date': date,  # 比赛日期
                'team_name': info.get(f'{team}_name', None),  # 战队名
                'team_flag': info.get(f'{team}_flag', None),  # 战队图标（若有 flag 可改字段名）
                'result': result,  # 获胜情况
                'kill': int(info.get(f'{team}_kill')) if info.get(f'{team}_kill') is not None else None,  # 总击杀
                'death': int(info.get(f'{team}_die')) if info.get(f'{team}_die') is not None else None,  # 总死亡
                'assist': int(info.get(f'{team}_asses')) if info.get(f'{team}_asses') is not None else None,  # 总助攻
                'attack': int(info.get(f'{team}_attack')) if info.get(f'{team}_attack') is not None else None,  # 总输出
                'money': convert_to_float(info.get(f'{team}_money')) if info.get(f'{team}_money') is not None else None,# 总经济
                'tower': info.get(f'{team}_tower', None),  # 战队推塔
                'small_dargon': info.get(f'{team}_small_dargon', None),  # 战队小龙
                'big_dargon': info.get(f'{team}_big_dargon', None),  # 战队大龙
                'riftHeraldKills': info.get(f'{team}_riftHeraldKills', None),  # 战队峡谷先锋
                'elder': info.get(f'{team}_elder', None),  # 战队远古巨龙
                'void_grub': info.get(f'{team}_void_grub', None),  # 战队巢虫 确定
                'firstHerald': team_dragon.get('firstHerald', None),  # 第一个峡谷先锋
                'firstBloodKill': team_dragon.get('firstBloodKill', None),  # 一血
                'firstTowerKill': team_dragon.get('firstTowerKill', None),  # 一塔
                'firstDragonKill': team_dragon.get('firstDragonKill', None),  # 一龙
                'firstBaronKill': team_dragon.get('firstBaronKill', None),  # 一巨龙
                'first5Kill': team_dragon.get('first5Kill', None),  # 首次五杀
                'first10Kill': team_dragon.get('first10Kill', None),  # 首次十杀
                'game_time': duration,  # 游戏时间（秒）
                'mvp': mvp if result == 1 else None,  # 获胜方MVP
                'beiguo': beiguo if result == 0 else None,  # 失败方背锅
                'player_a_id':info.get(f'{team}_star_a_name', None),
                'player_b_id':info.get(f'{team}_star_b_name', None),
                'player_c_id':info.get(f'{team}_star_c_name', None),
                'player_d_id':info.get(f'{team}_star_d_name', None),
                'player_e_id':info.get(f'{team}_star_e_name', None),
            }
            teams_data.append(team_data)


        # 选手数据 这里遍历红蓝方各五个位置，十个选手的数据
        list_positions = ['a', 'b', 'c', 'd', 'e']
        players_data = []
        for team in ['red', 'blue']:
            for pos in list_positions:
                prefix = f"{team}_star_{pos}_"
                prefix2 = f"{team}_hero_{pos}_"
                player_data = {
                    'name': info.get(f"{prefix}name", None),  # 选手名
                    'pic': info.get(f"{prefix}pic", None),  # 选手图片URL
                    'date': date,  # 比赛日期
                    'hero': info.get(f"{prefix2}name", None),  # 英雄名
                    'hero_lv': info.get(f"{prefix2}lv", None),  # 英雄等级
                    'kda': info.get(f"{prefix}kda", None),  # KDA
                    'kills': info.get(f"{prefix}kills", None),  # 击杀
                    'deaths': info.get(f"{prefix}deaths", None),  # 死亡
                    'assists': info.get(f"{prefix}assists", None),  # 助攻
                    'part': info.get(f"{prefix}part", None),  # 参团率
                    'atk': info.get(f"{prefix}atk_o", None),  # 总输出
                    'atk_p': info.get(f"{prefix}atk_p", None),  # 输出占比
                    'atk_m': info.get(f"{prefix}atk_m", None),  # 分均输出
                    'def_': info.get(f"{prefix}def_o", None),  # 承伤总量
                    'def_p': info.get(f"{prefix}def_p", None),  # 承伤占比
                    'def_m': info.get(f"{prefix}def_m", None),  # 分均承伤
                    'hits': info.get(f"{prefix}hits", None),  # 补刀数
                    'adc_m': info.get(f"{prefix}adc_m", None),  # 分均补刀
                    'money': info.get(f"{prefix}money_o", None),  # 总经济
                    'money_M': info.get(f"{prefix}money_M", None),  # 分钟经济
                    'wp_m': info.get(f"{prefix}wp_m", None),  # 分均插眼（待确认）
                    'mvp': int(info.get(f"{prefix}mvp", 0)),  # 是否MVP（1/0）
                    'beiguo': int(info.get(f"{prefix}beiguo", 0)),  # 是否背锅（1/0）
                    'team_name': info.get(f"{team}_name", None),  # 战队名
                    'position': pos,  # 位置
                    'game_time': duration,  # 游戏时间
                    'result': info.get(f"{team}_result", None),  # 胜负
                    'match_id': match_id  # 比赛ID
                }
                players_data.append(player_data)

        return {'matches': matches_data,'teams':teams_data, 'players': players_data}

    except Exception as e:
        print(f"[ERROR] 爬取比赛 {match_id} 时出错: {e}")
        return None

def is_chinese(string): # 因为数据中混有其他游戏，通过chinese判断可以快速筛选出lol比赛数据
    return any(u'\u4e00' <= ch <= u'\u9fff' for ch in string)


def convert_to_float(value):
    try:
        value_str = str(value).strip()
        if 'k' in value_str:
            return float(value_str.replace('k', '').strip()) * 1000
        else:
            return float(value_str)
    except Exception:
        return 0
