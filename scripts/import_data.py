from app import create_app, db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.services.spider import get_match_data

app = create_app()

with app.app_context():
    db.create_all()

    # 定义比赛 ID 的开始和结束 ID
    start_id = 59500  # 起始 ID
    end_id = 59900  # 结束 ID

    # 创建比赛 ID 列表，包含从 start_id 到 end_id 的所有 ID
    match_ids = list(range(start_id, end_id + 1))

    for match_id in match_ids:
        print(f"正在爬取比赛 ID: {match_id}")
        data = get_match_data(match_id)

        if data:
            try:
                # 判断该 match_id 是否已存在于数据库中
                existing_match = Match.query.filter_by(match_id=match_id).first()

                if existing_match:
                    # 如果数据已存在，跳过此次导入
                    print(f"比赛 ID {match_id} 已存在，跳过")
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

            except Exception as e:
                db.session.rollback()
                print(f"导入比赛 ID {match_id} 时发生错误，已跳过。错误信息: {e}")
        else:
            print(f"没有找到比赛数据：{match_id}")
