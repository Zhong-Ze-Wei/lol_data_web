import re
import os
import sys

# 添加项目根目录到Python路径，确保可以导入config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.services.spider import get_match_data
import config

# 更新config.py文件中的LAST_MATCH_ID
def update_last_match_id(match_id):
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.py')
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 使用正则表达式替换LAST_MATCH_ID的值
    updated_content = re.sub(
        r'LAST_MATCH_ID\s*=\s*\d+',
        f'LAST_MATCH_ID = {match_id}',
        content
    )
    
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(updated_content)
    
    # 更新运行时的配置值
    config.LAST_MATCH_ID = match_id
    print(f"已更新LAST_MATCH_ID为{match_id}")

app = create_app()

with app.app_context():
    db.create_all()

    # 从配置文件中读取上次爬取的最后一个比赛ID
    start_id = config.LAST_MATCH_ID  # 起始 ID
    
    # 连续未找到数据的计数器
    not_found_count = 0
    # 最大连续未找到数据的次数
    max_not_found = 100
    # 记录成功爬取的最大ID
    max_found_id = start_id - 1
    
    # 从start_id开始无限制地爬取，直到连续100个未找到数据
    match_id = start_id
    
    while not_found_count < max_not_found:
        print(f"正在爬取比赛 ID: {match_id}")
        data = get_match_data(match_id)

        if data:
            # 重置未找到数据的计数器
            not_found_count = 0
            # 更新成功爬取的最大ID
            max_found_id = match_id
            # 更新LAST_MATCH_ID
            update_last_match_id(match_id)
            try:
                # 判断该 match_id 是否已存在于数据库中
                existing_match = Match.query.filter_by(match_id=match_id).first()

                if existing_match:
                    # 如果数据已存在，跳过此次导入
                    print(f"比赛 ID {match_id} 已存在，跳过")
                    match_id += 1  # 即使跳过也要递增ID
                    continue  # 跳过当前比赛数据的导入

                # 第一步：保存 Match 数据
                match_data = data['matches'][0]
                match_record = Match(**match_data)
                db.session.add(match_record)

                print(f"比赛数据导入成功，match_id = {match_record.match_id}")

                # 第二步：保存 Team 数据
                teams = []
                for team_data in data['teams']:
                    team_data['match_id'] = match_record.match_id  # 使用 match_id 而非 id
                    team_record = Team(**team_data)
                    teams.append(team_record)
                # 批量添加战队数据
                db.session.bulk_save_objects(teams)

                # 第三步：保存 Player 数据
                players = []
                for player_data in data['players']:
                    player_data['match_id'] = match_record.match_id  # 使用 match_id 而非 id
                    player_record = Player(**player_data)
                    players.append(player_record)
                # 批量添加选手数据
                db.session.bulk_save_objects(players)

                # 统一提交
                db.session.commit()
                print(f"战队和选手数据导入成功！比赛 ID: {match_id}")
                match_id += 1  # 成功导入后递增ID

            except Exception as e:
                db.session.rollback()
                print(f"导入比赛 ID {match_id} 时发生错误，已跳过。错误信息: {e}")
                match_id += 1  # 出错后也要递增ID
        else:
            # 如果连续多次未找到数据，则认为已经爬取完毕
            not_found_count += 1
            print(f"没有找到比赛数据：{match_id}，连续未找到: {not_found_count}/{max_not_found}")
            match_id += 1  # 未找到数据时也递增ID
