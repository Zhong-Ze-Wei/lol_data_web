"""校验、规范化及原子入库；单局 resultID 是三张业务表的关联键。"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, or_

from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import SyncTask, utc_now
from app.services.source_identity import recover_slot_name, source_player_id
from app.services.team_names import resolve_bo_identity, resolve_team_names, winner_identity_error


class InvalidResult(ValueError):
    pass


class NonLOLResult(InvalidResult):
    pass


class PendingResult(InvalidResult):
    pass


class SourceIncompleteResult(InvalidResult):
    """已发布历史战报确有缺项；保留原始依据，不能制造完整的业务行。"""

    pass


@dataclass
class IngestOutcome:
    result_id: int
    status: str
    error: str = None

    def to_dict(self):
        return {'result_id': self.result_id, 'status': self.status, 'error': self.error}


def numeric(value, field, integer=False, required=False, percentage=False):
    if value is None or str(value).strip() in ('', '-', '--', 'N/A', 'null'):
        if required:
            raise InvalidResult(f'{field}: 缺少必要数值')
        return None
    if field.endswith('kda') and str(value).lower() in ('perfect', 'infinity', 'inf', '∞'):
        return None  # 零死亡的无限 KDA 不伪造为 0。
    text = str(value).strip().replace(',', '').removesuffix('%')
    multiplier = 1000 if text.lower().endswith('k') else 1
    try:
        result = float(text[:-1] if multiplier == 1000 else text) * multiplier
    except (TypeError, ValueError) as exc:
        raise InvalidResult(f'{field}: 无效数值 {value!r}') from exc
    if not math.isfinite(result) or result < 0:
        raise InvalidResult(f'{field}: 非有限或负数 {value!r}')
    if percentage and result > 100:
        raise InvalidResult(f'{field}: 百分比不在 0–100 范围 {value!r}')
    if integer and not result.is_integer():
        raise InvalidResult(f'{field}: 需要整数 {value!r}')
    return int(result) if integer else result


def _winner(value, field):
    parsed = numeric(value, field, integer=True, required=True)
    if parsed not in (0, 1):
        raise InvalidResult(f'{field}: 胜负标志必须为 0 或 1')
    return parsed


def has_finished_lol_evidence(payload, result_id):
    """无赛程旧单局的结束证据；缺证据仍走严格校验，不猜赛年或结束状态。"""
    if not isinstance(payload, dict) or payload.get('code') not in (200, '200'):
        return False
    data = payload.get('data')
    if not isinstance(data, dict) or str(data.get('gameID')) != '1':
        return False
    info = data.get('result_list')
    if not isinstance(info, dict):
        return False
    names = [info.get(f'{side}_name') for side in ('red', 'blue')]
    if any(not isinstance(name, str) or not name.strip() for name in names) or names[0] == names[1]:
        return False
    try:
        if data.get('resultID') and int(data['resultID']) != int(result_id):
            return False
        results = {side: _winner(info.get(f'{side}_result'), f'{side}_result') for side in ('red', 'blue')}
        if sum(results.values()) != 1:
            return False
        ids = {side: numeric(info.get(f'{side}_teamID'), f'{side}_teamID', integer=True, required=True)
               for side in ('red', 'blue')}
        winner_id = numeric(info.get('win_teamID'), 'win_teamID', integer=True, required=True)
        if min(ids.values()) <= 0 or ids['red'] == ids['blue'] or winner_id != ids[next(side for side in ids if results[side])]:
            return False
        for side in ('red', 'blue'):
            kills = numeric(info.get(f'{side}_kill'), f'{side}_kill', integer=True)
            slot_kills = [numeric(info.get(f'{side}_star_{pos}_kills'), f'{side}_star_{pos}_kills', integer=True)
                          for pos in 'abcde']
            if kills is not None and all(value is not None for value in slot_kills) and kills != sum(slot_kills):
                return False
        return True
    except (TypeError, ValueError):
        return False


def _source_duration(info, allow_incomplete, missing):
    try:
        minutes = numeric(info.get('game_time_m'), 'game_time_m', integer=True, required=not allow_incomplete)
        seconds = numeric(info.get('game_time_s'), 'game_time_s', integer=True, required=not allow_incomplete)
        if seconds is not None and seconds >= 60:
            raise InvalidResult(f"game_time_s 必须小于 60，来源值 {info.get('game_time_s')!r}")
    except InvalidResult as exc:
        if not allow_incomplete:
            raise
        missing.append(str(exc))
        return None
    duration = minutes * 60 + seconds if minutes is not None and seconds is not None else None
    # ScoreGG 的旧详情以 00:00 / 00:01 占位；不能参与分钟指标分母。
    if duration is None or duration <= 1:
        if not allow_incomplete:
            raise PendingResult('单局时长尚未产生，00:00 / 00:01 为来源占位')
        missing.append(f"game_time: 来源缺项或占位 {info.get('game_time_m')!r}:{info.get('game_time_s')!r}")
        return None
    return duration


def _known_nonzero_kills(info, teams):
    """整族占位判断需要十人击杀与双方战队汇总互相印证。"""
    for side, team in zip(('red', 'blue'), teams):
        try:
            kills = [numeric(info.get(f'{side}_star_{position}_kills'),
                             f'{side}_star_{position}_kills', integer=True) for position in 'abcde']
        except InvalidResult:
            return False  # 未具名槽仍可提供原件证据；无效击杀不作为清空其他指标的依据。
        if any(value is None for value in kills):
            return False
        if team['kill'] is None or team['kill'] != sum(kills):
            return False
    return sum(team['kill'] for team in teams) > 0


def _source_fields_all_zero(info, fields):
    """缺名槽也须有有效原件零值，坏原件只取消本族判断，不拒绝其余具名行。"""
    try:
        return all(numeric(info.get(field), field) == 0 for field in fields)
    except InvalidResult:
        return False


def _clear_missing_metric_groups(info, teams, players):
    """只有跨十人和双方的整族明确零，才视为未记录；局部真实零保留。"""
    if not _known_nonzero_kills(info, teams):
        return []
    slots = [(side, position) for side in ('red', 'blue') for position in 'abcde']
    damage_keys = [f'{side}_star_{position}_{field}' for side, position in slots
                   for field in ('atk_o', 'def_o')] + ['red_attack', 'blue_attack']
    economy_keys = [f'{side}_star_{position}_money_o' for side, position in slots] + ['red_money', 'blue_money']
    cs_keys = economy_keys + [f'{side}_star_{position}_hits' for side, position in slots]
    combat_keys = [f'{side}_{field}' for side in ('red', 'blue') for field in ('result', 'kill')]
    combat_keys += [f'{side}_star_{position}_kills' for side, position in slots]
    rules = (
        ('damage', damage_keys,
         {'atk': 'atk_o', 'atk_p': 'atk_p', 'atk_m': 'atk_m', 'def_': 'def_o', 'def_p': 'def_p', 'def_m': 'def_m'},
         {'attack': 'attack'}, '十人伤害/承伤及双方伤害整组来源零与可靠战果矛盾，已排除该族'),
        ('economy', economy_keys, {'money': 'money_o', 'money_M': 'money_M'}, {'money': 'money'},
         '十人及双方经济整组来源零与可靠战果矛盾，已排除该族'),
        ('cs', cs_keys, {'hits': 'hits', 'adc_m': 'adc_m'}, {},
         '经济族已排除且十人补刀整组来源零；疑似未记录，已排除补刀族'),
    )
    players_by_slot = {(player['team_name'], player['position']): player for player in players}
    invalid_groups = []
    for group, source_keys, player_fields, team_fields, reason in rules:
        # None、缺键和空字符串不等于明确零；不能凭不完整的整族资料扩大判断。
        if not _source_fields_all_zero(info, source_keys):
            continue
        cleared_fields = []
        for side, team in zip(('red', 'blue'), teams):
            for field, source in team_fields.items():
                source_field = f'{side}_{source}'
                if team[field] == 0:
                    team[field] = None
                    cleared_fields.append({'table': 'teams', 'team_name': team['team_name'], 'field': field,
                                           'source_field': source_field, 'source_value': info[source_field]})
            for position in 'abcde':
                player = players_by_slot.get((team['team_name'], position))
                if player is None:
                    continue  # 原始十槽统计证据不制造缺失身份，只清现有具名行。
                for field, source in player_fields.items():
                    source_field = f'{side}_star_{position}_{source}'
                    if player[field] == 0 and numeric(info.get(source_field), source_field) == 0:
                        player[field] = None
                        cleared_fields.append({'table': 'players', 'team_name': player['team_name'],
                                               'position': position, 'field': field, 'source_field': source_field,
                                               'source_value': info[source_field]})
        invalid_groups.append({'group': group, 'reason': reason,
                               'evidence': {key: info[key] for key in source_keys + combat_keys},
                               'cleared_fields': cleared_fields})
    return invalid_groups


def _known_identity_id(value):
    text = str(value).strip() if value is not None else ''
    return int(text) if text.isascii() and text.isdigit() and int(text) > 0 else None


def _check_schedule_binding(schedule, info, detail_series_id):
    """只拒绝明确原行中的已知身份矛盾；缺项不能遮住其它已知冲突。"""
    row = schedule.get('source_row')
    if not isinstance(row, dict):
        return
    series_ids = [_known_identity_id(value) for value in
                  (detail_series_id, schedule.get('series_id'), row.get('matchID'))]
    if len({identifier for identifier in series_ids if identifier is not None}) > 1:
        raise InvalidResult('赛程 BO 身份冲突：详情、声明系列与原行 ID 不一致')
    detail_ids = tuple(_known_identity_id(info.get(f'{side}_teamID')) for side in ('red', 'blue'))
    schedule_ids = tuple(_known_identity_id(row.get(f'teamID_{side}')) for side in ('a', 'b'))
    auxiliary_ids = tuple(_known_identity_id(info.get(f'teamID_{side}')) for side in ('a', 'b'))
    for label, identifiers in (('详情', detail_ids), ('赛程', schedule_ids)):
        if None not in identifiers and len(set(identifiers)) != 2:
            raise InvalidResult(f'{label}双方队伍身份重复')
    if None not in detail_ids:
        for label, identifiers in (('赛程', schedule_ids), ('辅助', auxiliary_ids)):
            if any(identifier is not None and identifier not in detail_ids for identifier in identifiers):
                raise InvalidResult(f'{label}队伍身份不属于详情双方')
        if None not in auxiliary_ids and set(auxiliary_ids) != set(detail_ids):
            raise InvalidResult('辅助双方队伍身份重复或不一致')
    if None not in schedule_ids:
        if any(identifier is not None and identifier not in schedule_ids for identifier in detail_ids):
            raise InvalidResult('详情队伍身份不属于赛程双方')


def normalize_result(payload, result_id, schedule=None, allow_incomplete=False, names_by_source_id=None,
                     prior_team_name_provenance=None):
    if not isinstance(payload, dict):
        raise InvalidResult('详情返回值必须为 JSON 对象')
    if payload.get('code', 200) not in (200, '200'):
        raise InvalidResult(f"上游返回失败状态，code={payload.get('code')}, message={payload.get('message')}")
    data = payload.get('data')
    if not isinstance(data, dict) or not data:
        raise PendingResult('上游尚无单局详情')
    result_id = _known_identity_id(result_id)
    if result_id is None:
        raise InvalidResult('请求的 result_id 必须是明确的正整数')
    if 'resultID' in data and _known_identity_id(data['resultID']) != result_id:
        raise InvalidResult('返回的 resultID 无效或与请求的单局 ID 不一致')
    game_id = _known_identity_id(data.get('gameID'))
    if game_id is None:
        raise InvalidResult('上游 gameID 缺失或不是明确的正整数，无法确认游戏')
    if game_id != 1:
        raise NonLOLResult(f"gameID={data['gameID']}，不是 LOL")
    info = data.get('result_list')
    if not isinstance(info, dict) or not info:
        raise PendingResult('result_list 尚未生成')
    bo_identity = resolve_bo_identity(data)
    if bo_identity['error']:
        raise InvalidResult(f"详情所属 BO 身份冲突或格式无效：{bo_identity['error']}")
    detail_names = {side: info.get(f'{side}_name') for side in ('red', 'blue')}
    names, team_name_provenance = resolve_team_names(data, schedule, detail_names, prior_team_name_provenance)
    if any(not isinstance(name, str) or not name.strip() for name in names.values()):
        exception = SourceIncompleteResult if allow_incomplete else InvalidResult
        raise exception('详情缺少完整的双方队名')
    if names['red'] == names['blue']:
        raise InvalidResult('双方队名相同，无法形成正确自然键')
    results = {side: _winner(info.get(f'{side}_result'), f'{side}_result') for side in names}
    if sum(results.values()) != 1:
        raise PendingResult('双方胜负尚未确定')
    missing = []
    duration = _source_duration(info, allow_incomplete, missing)
    winner_error = winner_identity_error(info, results)
    if winner_error:
        raise InvalidResult(f'详情胜方身份冲突或格式无效：{winner_error}')
    schedule = schedule or {}
    _check_schedule_binding(schedule, info, bo_identity['series_id'])
    date = schedule.get('scheduled_at')
    date_source = 'schedule' if date else 'unknown'
    if isinstance(date, str):
        date = datetime.fromisoformat(date)
    if date is None and data.get('updated_at'):
        try:
            date = datetime.strptime(data['updated_at'], '%Y%m%d%H%M%S')
        except (TypeError, ValueError) as exc:
            raise InvalidResult('updated_at 日期无效') from exc
        date_source = 'updated_at'
    mvp = (data.get('max_mvp') or {}).get('nickname')
    beiguo = (data.get('max_beiguo') or {}).get('nickname')
    source_series = bo_identity['series_id']
    series_id = schedule.get('series_id') or source_series
    if source_series and schedule.get('series_id') and source_series != int(schedule['series_id']):
        raise InvalidResult('赛程 series_id 与详情所属 BO 系列不一致')
    match = {
        'match_id': result_id, 'series_id': series_id,
        'tournament_id': schedule.get('tournament_id'), 'tournament_name': schedule.get('tournament_name'),
        'date': date, 'date_source': date_source, 'game_time': duration,
        'red_team_name': names['red'], 'blue_team_name': names['blue'],
        'win_team_name': next(names[side] for side in names if results[side] == 1),
        'mvp': mvp, 'source': 'scoregg', 'verified': True,
        'team_name_provenance': team_name_provenance,
    }
    teams = []
    players = []
    invalid_percentages = []
    missing_roster_slots = []
    recovered_player_names = []
    team_stats = {
        'kill': 'kill', 'death': 'die', 'assist': 'asses', 'attack': 'attack', 'money': 'money',
        'tower': 'tower', 'small_dargon': 'small_dargon', 'big_dargon': 'big_dargon',
        'riftHeraldKills': 'riftHeraldKills', 'elder': 'elder', 'void_grub': 'void_grub',
    }
    player_stats = {
        'kda': 'kda', 'kills': 'kills', 'deaths': 'deaths', 'assists': 'assists',
        'part': 'part', 'atk': 'atk_o', 'atk_p': 'atk_p', 'atk_m': 'atk_m',
        'def_': 'def_o', 'def_p': 'def_p', 'def_m': 'def_m', 'adc_m': 'adc_m',
        'money': 'money_o', 'money_M': 'money_M', 'wp_m': 'wp_m', 'hits': 'hits',
        'mvp': 'mvp', 'beiguo': 'beiguo',
    }
    player_ints = {'kills', 'deaths', 'assists', 'atk', 'def_', 'money', 'hits', 'mvp', 'beiguo'}
    for side in ('red', 'blue'):
        team = {
            'match_id': result_id, 'date': date, 'team_name': names[side],
            'team_flag': info.get(f'{side}_flag'), 'result': results[side], 'game_time': duration,
            'mvp': mvp if results[side] else None, 'beiguo': beiguo if not results[side] else None,
        }
        for target, source in team_stats.items():
            key = f'{side}_{source}'
            team[target] = numeric(info.get(key), key, integer=target != 'money')
        dragon = (data.get('dragon_list') or {}).get(side) or {}
        for field in ('firstHerald', 'firstBloodKill', 'firstTowerKill', 'firstDragonKill',
                      'firstBaronKill', 'first5Kill', 'first10Kill'):
            team[field] = numeric(dragon.get(field), f'{side}.{field}', integer=True)
        for pos in 'abcde':
            prefix = f'{side}_star_{pos}_'
            name = info.get(prefix + 'name')
            if not isinstance(name, str) or not name.strip():
                recovered = recover_slot_name(data, side, pos, names_by_source_id) if allow_incomplete else None
                if recovered:
                    name = recovered['name']
                    recovered_player_names.append(recovered)
                elif not allow_incomplete:
                    raise InvalidResult(f'{prefix}name: 缺少选手，完整单局需要 10 位选手')
                else:
                    reason = f'{prefix}name: 来源缺少选手昵称，未制造身份'
                    missing.append(reason)
                    missing_roster_slots.append({'team_name': names[side], 'position': pos, 'team_color': side,
                                                 'source_player_id': source_player_id(info.get(prefix + 'playerID')),
                                                 'source_field': prefix + 'name', 'reason': reason})
                    team[f'player_{pos}_id'] = None
                    continue
            team[f'player_{pos}_id'] = name
            player = {
                'match_id': result_id, 'date': date, 'name': name, 'pic': info.get(prefix + 'pic'),
                'source_player_id': source_player_id(info.get(prefix + 'playerID')),
                'hero': info.get(f'{side}_hero_{pos}_name'),
                'hero_lv': numeric(info.get(f'{side}_hero_{pos}_lv'), 'hero_lv', integer=True),
                'team_name': names[side], 'position': pos, 'game_time': duration,
                'result': str(results[side]),
            }
            for target, source in player_stats.items():
                key = prefix + source
                is_percentage = target in ('part', 'atk_p', 'def_p')
                try:
                    player[target] = numeric(
                        info.get(key), key, integer=target in player_ints,
                        required=target in ('kills', 'deaths', 'assists') and not allow_incomplete,
                        percentage=is_percentage,
                    )
                except InvalidResult as exc:
                    if not allow_incomplete or not is_percentage:
                        raise
                    player[target] = None
                    missing.append(str(exc))
                    invalid_percentages.append({'team_name': names[side], 'position': pos, 'field': target,
                                                'source_field': key, 'source_value': info.get(key), 'reason': str(exc)})
                if target in ('kills', 'deaths', 'assists') and player[target] is None:
                    missing.append(key)
            players.append(player)
        teams.append(team)
    invalid_metric_groups = _clear_missing_metric_groups(info, teams, players)
    identifiers = [player['source_player_id'] for player in players if player['source_player_id'] is not None]
    if len(set(identifiers)) != len(identifiers) or any(len(identifier) > 100 for identifier in identifiers):
        raise InvalidResult('详情来源选手 ID 重复或超过字段长度')
    missing.extend(group['reason'] for group in invalid_metric_groups)
    normalized = {'matches': [match], 'teams': teams, 'players': players}
    if missing:
        normalized['source_incomplete'] = missing
    if invalid_percentages:
        normalized['invalid_percentages'] = invalid_percentages
    if missing_roster_slots:
        normalized['missing_roster_slots'] = missing_roster_slots
    if recovered_player_names:
        normalized['recovered_player_names'] = recovered_player_names
    if invalid_metric_groups:
        normalized['invalid_metric_groups'] = invalid_metric_groups
    if duration is None:
        normalized['invalid_duration'] = True
    return normalized


def bulk_upsert(model, rows, keys, session=None, preserve_nulls=True):
    if not rows:
        return
    session = session or db.session
    dialect = session.get_bind().dialect.name
    columns = set().union(*(row.keys() for row in rows))
    records = [{key: row.get(key) for key in columns} for row in rows]
    if dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert

        statement = insert(model.__table__)
        statement = statement.on_conflict_do_update(
            index_elements=keys,
            set_={key: (func.coalesce(getattr(statement.excluded, key), model.__table__.c[key])
                       if preserve_nulls else getattr(statement.excluded, key))
                  for key in columns if key not in keys},
        )
    elif dialect in ('mysql', 'mariadb'):
        from sqlalchemy.dialects.mysql import insert

        statement = insert(model.__table__)
        statement = statement.on_duplicate_key_update(
            **{key: (func.coalesce(getattr(statement.inserted, key), model.__table__.c[key])
                    if preserve_nulls else getattr(statement.inserted, key))
               for key in columns if key not in keys},
        )
    else:
        raise ValueError(f'不支持批量导入的数据库: {dialect}')
    session.execute(statement, records)


def get_task(result_id=None, schedule=None, run_id=None):
    schedule = schedule or {}
    key = f'result:{int(result_id)}' if result_id is not None else f"series:{int(schedule['series_id'])}"
    task = db.session.query(SyncTask).filter_by(task_key=key).first()
    if task is None:
        task = SyncTask(task_key=key, result_id=result_id, attempts=0)
        db.session.add(task)
    for field in ('series_id', 'tournament_id', 'tournament_name', 'scheduled_at'):
        if schedule.get(field) is not None:
            setattr(task, field, schedule[field])
    if run_id is not None:
        task.run_id = run_id
    return task


def start_task(result_id=None, schedule=None, run_id=None):
    task = get_task(result_id, schedule, run_id)
    task.status = 'running'
    task.attempts = (task.attempts or 0) + 1
    task.updated_at = utc_now()
    db.session.commit()
    return task


def finish_task(result_id, status, error=None, schedule=None, run_id=None):
    task = get_task(result_id, schedule, run_id)
    if task.status != 'running':
        task.attempts = (task.attempts or 0) + 1
    task.status = status
    task.last_error = error
    task.updated_at = utc_now()
    if status == 'failed':
        task.failure_count = (task.failure_count or 0) + 1
    elif status in ('imported', 'skipped', 'pending', 'source_incomplete'):
        task.failure_count = 0
    task.next_retry_at = (
        utc_now() + timedelta(hours=24 if status == 'pending' else min(24, 2 ** min(task.attempts, 5)))
        if status in ('pending', 'failed') else None
    )
    if status == 'imported':
        task.imported_at = utc_now()
    return task


def mark_failure(result_id, error, schedule=None, run_id=None, status='failed'):
    db.session.rollback()
    finish_task(result_id, status, str(error), schedule, run_id)
    db.session.commit()
    return IngestOutcome(result_id, status, str(error))


def _rekey_verified_team_names(existing, data):
    """同局身份已确认的更名原位更新；不同昵称不继承旧槽的可选指标。"""
    match = data['matches'][0]
    proof = match['team_name_provenance']
    if (existing is None or not existing.verified or existing.source not in ('scoregg', 'scoregg_metadata')
            or existing.series_id != match['series_id'] or proof['selected_source'] != 'schedule'):
        return
    old_names = {'red': existing.red_team_name, 'blue': existing.blue_team_name}
    new_names = proof['selected_names']
    if old_names == new_names:
        return
    previous = existing.team_name_provenance
    ids = proof['detail']['team_ids']
    if previous and previous['detail']['series_id'] == match['series_id']:
        old_ids = previous['detail']['team_ids']
        if None in old_ids.values() or set(old_ids.values()) != set(ids.values()) or len(set(old_ids.values())) != 2:
            return
        mapping = {side: next(color for color in ids if ids[color] == identifier)
                   for side, identifier in old_ids.items()}
    elif old_names == proof['detail']['names']:
        mapping = {'red': 'red', 'blue': 'blue'}
    else:
        return  # 旧名称与任何具备同局身份的来源都不一致，不挪用其可选统计。
    db.session.query(Player).filter(Player.match_id == existing.match_id,
                                    or_(Player.team_name.is_(None), ~Player.team_name.in_(old_names.values()))
                                    ).delete(synchronize_session=False)
    db.session.query(Team).filter(Team.match_id == existing.match_id,
                                  or_(Team.team_name.is_(None), ~Team.team_name.in_(old_names.values()))
                                  ).delete(synchronize_session=False)
    prefix = f'__team_rekey_{uuid4().hex}_'
    renamed = []
    for side, old_name in old_names.items():
        target = new_names[mapping[side]]
        temporary = prefix + side
        for model in (Team, Player):
            db.session.query(model).filter_by(match_id=existing.match_id, team_name=old_name).update(
                {'team_name': temporary}, synchronize_session=False)
        renamed.append((temporary, target))
    for temporary, target in renamed:
        for model in (Team, Player):
            db.session.query(model).filter_by(match_id=existing.match_id, team_name=temporary).update(
                {'team_name': target}, synchronize_session=False)
    db.session.expire_all()


def _discard_changed_player_slots(data):
    """自然键仍是同局同队同位置；换昵称时不能 COALESCE 继承前一选手数据。"""
    incoming = {(row['team_name'], row['position']): row['name'] for row in data['players']}
    result_id = data['matches'][0]['match_id']
    for player in db.session.query(Player).filter_by(match_id=result_id).all():
        key = (player.team_name, player.position)
        if key in incoming and incoming[key] != player.name:
            db.session.delete(player)
    db.session.flush()


def _upsert_identified_players(rows, preserve_nulls):
    """有来源 ID 的出场原位升级；先腾出角色键，避免换位时瞬间唯一键冲突。"""
    result_id = rows[0]['match_id']
    existing = db.session.query(Player).filter_by(match_id=result_id).all()
    by_id = {player.source_player_id: player for player in existing if player.source_player_id is not None}
    by_slot = {(player.team_name, player.position): player for player in existing if player.position is not None}
    updates, used = [], set()
    for row in rows:
        identifier = row.get('source_player_id')
        player = by_id.get(identifier) if identifier is not None else None
        if player is None and row['position'] is not None:
            slot = by_slot.get((row['team_name'], row['position']))
            if slot is not None and slot.source_player_id is not None and identifier is None:
                raise InvalidResult('完整刷新缺少已知出场的来源选手 ID，不能清除身份或重建主键')
            if slot is not None and slot.name == row['name'] and slot.source_player_id in (None, identifier):
                player = slot
        if player is not None and player.id in used:
            raise InvalidResult('两个来源选手不能升级同一出场行')
        if player is not None:
            used.add(player.id)
        updates.append((player, row))
    slots = {(row['team_name'], row['position']) for row in rows if row['position'] is not None}
    for player in existing:
        if player.id in used:
            player.position = f'__source_upgrade_{uuid4().hex}'
        elif (player.team_name, player.position) in slots:
            db.session.delete(player)
    db.session.flush()
    for player, row in updates:
        keep_optional = preserve_nulls and player is not None and player.name == row['name']
        if player is None:
            player = Player()
            db.session.add(player)
        for field, value in row.items():
            if value is not None or not keep_optional or field in ('position', 'source_player_id'):
                setattr(player, field, value)
    db.session.flush()


def ingest_metadata_result(payload, result_id, schedule, archive, run_id=None):
    """独立真实基础来源只补缺项；已核验完整 CDN 详情拥有更高优先级。"""
    from app.services.metadata_snapshot import normalize_metadata_snapshot
    from app.services.spider import SourceError

    try:
        data = normalize_metadata_snapshot(payload, result_id, schedule, archive)
        existing = db.session.query(Match).filter_by(match_id=result_id).first()
        if existing is not None and existing.verified and existing.source == 'scoregg':
            return IngestOutcome(result_id, 'skipped', '已核验 CDN 详情保留；metadata 不降级完整来源')
        if existing is not None and existing.verified and existing.source == 'scoregg_metadata':
            _check_metadata_roster_refresh(existing, data)
            _rekey_verified_team_names(existing, data)
        else:
            # 旧 CSV 未核验身份不附着新来源 ID，不继承其猜测角色或指标。
            db.session.query(Player).filter_by(match_id=result_id).delete(synchronize_session=False)
            db.session.query(Team).filter_by(match_id=result_id).delete(synchronize_session=False)
        bulk_upsert(Match, data['matches'], ['match_id'], preserve_nulls=False)
        for model, rows in ((Team, data['teams']), (Player, data['players'])):
            nullable = [column.name for column in model.__table__.columns if column.nullable and not column.primary_key]
            for row in rows:
                for field in nullable:
                    row.setdefault(field, None)
        bulk_upsert(Team, data['teams'], ['match_id', 'team_name'], preserve_nulls=False)
        _upsert_identified_players(data['players'], preserve_nulls=False)
        error = ', '.join(data['source_incomplete'])
        finish_task(result_id, 'source_incomplete', error, schedule, run_id)
        db.session.commit()
        return IngestOutcome(result_id, 'source_incomplete', error)
    except (SQLAlchemyError, SourceError, OSError, TypeError, ValueError) as exc:
        return mark_failure(result_id, exc, schedule, run_id)


def _check_metadata_roster_refresh(existing, data):
    """真实色方可以互换，同一来源选手的已知战队身份不能随槽位换队。"""
    match = data['matches'][0]
    old_players = db.session.query(Player).filter_by(match_id=existing.match_id).all()
    old_ids = {player.source_player_id for player in old_players}
    new_ids = {player['source_player_id'] for player in data['players']}
    if (existing.series_id != match['series_id'] or len(old_players) != 10 or len(data['players']) != 10
            or None in new_ids or old_ids != new_ids):
        raise InvalidResult('刷新来源不能证明与已存 metadata 相同的十位选手身份')
    old_proof = existing.team_name_provenance
    if not isinstance(old_proof, dict) or not isinstance(old_proof.get('detail'), dict):
        raise InvalidResult('已存 metadata 缺少可靠战队身份依据')
    old_team_ids = old_proof['detail']['team_ids']
    new_team_ids = match['team_name_provenance']['detail']['team_ids']
    if (None in new_team_ids.values() or len(set(new_team_ids.values())) != 2
            or set(old_team_ids.values()) != set(new_team_ids.values())):
        raise InvalidResult('刷新来源不能证明 metadata 的相同双方战队 ID')
    old_teams = {getattr(existing, f'{side}_team_name'): old_team_ids[side] for side in ('red', 'blue')}
    new_teams = {match[f'{side}_team_name']: new_team_ids[side] for side in ('red', 'blue')}
    previous_teams = {player.source_player_id: old_teams.get(player.team_name) for player in old_players}
    if any(previous_teams[player['source_player_id']] != new_teams.get(player['team_name'])
           for player in data['players']):
        raise InvalidResult('刷新来源选手 ID 的已知战队归属与 metadata 矛盾')


def ingest_result(payload, result_id, schedule=None, run_id=None, allow_incomplete=False, replace_existing=False,
                  names_by_source_id=None):
    try:
        existing = db.session.query(Match).filter_by(match_id=result_id).first()
        previous = (existing.team_name_provenance if existing is not None
                    and existing.source == 'scoregg' and existing.verified else None)
        data = normalize_result(payload, result_id, schedule, allow_incomplete, names_by_source_id, previous)
        if existing is not None and existing.verified and existing.source == 'scoregg_metadata':
            _check_metadata_roster_refresh(existing, data)
    except SQLAlchemyError as exc:
        return mark_failure(result_id, exc, schedule, run_id)
    except NonLOLResult as exc:
        # 原始 CSV 与响应 JSON 留档；仅清理派生库中已被明确证实不是 LOL 的旧记录。
        existing = db.session.query(Match).filter_by(match_id=result_id, source='legacy', verified=False).first()
        if existing is not None:
            db.session.query(Player).filter_by(match_id=result_id).delete(synchronize_session=False)
            db.session.query(Team).filter_by(match_id=result_id).delete(synchronize_session=False)
            db.session.delete(existing)
            finish_task(result_id, 'skipped', str(exc), schedule, run_id)
            db.session.commit()
            return IngestOutcome(result_id, 'skipped', str(exc))
        return mark_failure(result_id, exc, schedule, run_id, 'skipped')
    except (PendingResult, SourceIncompleteResult) as exc:
        status = 'source_incomplete' if allow_incomplete else 'pending'
        return mark_failure(result_id, exc, schedule, run_id, status)
    except (InvalidResult, TypeError, ValueError) as exc:
        return mark_failure(result_id, exc, schedule, run_id)
    try:
        preserve_nulls = (not replace_existing and existing is not None
                          and existing.source in ('scoregg', 'scoregg_metadata') and existing.verified)
        if existing is not None and existing.date_source == 'schedule' and data['matches'][0]['date_source'] != 'schedule':
            data['matches'][0]['date'] = existing.date
            data['matches'][0]['date_source'] = 'schedule'
            for row in data['teams'] + data['players']:
                row['date'] = existing.date
        # 未核验旧值不能借本次 gameID 证据升为来源数据；首次核验按原始详情清除缺项。
        # 只有此前已核验的 ScoreGG 记录，才允许保留早前有来源依据的可选指标。
        _rekey_verified_team_names(existing, data)
        has_ids = any(row.get('source_player_id') is not None for row in data['players'])
        if preserve_nulls and not has_ids:
            _discard_changed_player_slots(data)
        bulk_upsert(Match, data['matches'], ['match_id'], preserve_nulls=preserve_nulls)
        bulk_upsert(Team, data['teams'], ['match_id', 'team_name'], preserve_nulls=preserve_nulls)
        if has_ids:
            _upsert_identified_players(data['players'], preserve_nulls)
        else:
            bulk_upsert(Player, data['players'], ['match_id', 'team_name', 'position'], preserve_nulls=preserve_nulls)
        # 来源明确给出占位/非法时长时，先前的值也不能继续作为统计分母。
        if data.get('invalid_duration'):
            for model in (Match, Team, Player):
                db.session.query(model).filter_by(match_id=result_id).update(
                    {'game_time': None}, synchronize_session=False)
        # 空昵称不附着旧 CSV 中猜测的身份；保留可核验的双方与其余九人。
        for slot in data.get('missing_roster_slots', []):
            db.session.query(Player).filter_by(match_id=result_id, team_name=slot['team_name'],
                                              position=slot['position']).delete(synchronize_session=False)
            db.session.query(Team).filter_by(match_id=result_id, team_name=slot['team_name']).update(
                {f"player_{slot['position']}_id": None}, synchronize_session=False)
        # 明确无效的来源百分比必须留空；已核验旧值的 COALESCE 保护不适用于这些字段。
        for invalid in data.get('invalid_percentages', []):
            db.session.query(Player).filter_by(match_id=result_id, team_name=invalid['team_name'],
                                              position=invalid['position']).update(
                {invalid['field']: None}, synchronize_session=False)
        # 已证实的整族占位零覆盖 COALESCE；按自然键合并字段，仍在本局事务中清 NULL。
        forced_clears = {}
        for group in data.get('invalid_metric_groups', []):
            for cleared in group['cleared_fields']:
                key = (cleared['table'], cleared['team_name'], cleared.get('position'))
                forced_clears.setdefault(key, {})[cleared['field']] = None
        for (table, team_name, position), values in forced_clears.items():
            model = Player if table == 'players' else Team
            query = db.session.query(model).filter_by(match_id=result_id, team_name=team_name)
            if table == 'players':
                query = query.filter_by(position=position)
            query.update(values, synchronize_session=False)
        # 线上完整结果替换历史残缺/冲突多出来的自然键，现有正确记录仍原位更新。
        team_names = [team['team_name'] for team in data['teams']]
        db.session.query(Player).filter(Player.match_id == result_id, or_(
            Player.team_name.is_(None), ~Player.team_name.in_(team_names),
            Player.position.is_(None), ~Player.position.in_(list('abcde')),
        )).delete(synchronize_session=False)
        db.session.query(Team).filter(Team.match_id == result_id, or_(
            Team.team_name.is_(None), ~Team.team_name.in_(team_names),
        )).delete(synchronize_session=False)
        status = 'source_incomplete' if data.get('source_incomplete') else 'imported'
        error = ', '.join(data['source_incomplete']) if data.get('source_incomplete') else None
        finish_task(result_id, status, error, schedule=schedule, run_id=run_id)
        db.session.commit()
    except (SQLAlchemyError, InvalidResult) as exc:
        return mark_failure(result_id, exc, schedule, run_id)
    return IngestOutcome(result_id, status, error)
