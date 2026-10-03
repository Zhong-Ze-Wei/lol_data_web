"""校验、规范化及原子入库；单局 resultID 是三张业务表的关联键。"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, or_

from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import SyncTask, utc_now


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


def normalize_result(payload, result_id, schedule=None, allow_incomplete=False):
    if not isinstance(payload, dict):
        raise InvalidResult('详情返回值必须为 JSON 对象')
    if payload.get('code', 200) not in (200, '200'):
        raise InvalidResult(f"上游返回失败状态，code={payload.get('code')}, message={payload.get('message')}")
    data = payload.get('data')
    if not isinstance(data, dict) or not data:
        raise PendingResult('上游尚无单局详情')
    if 'gameID' not in data:
        raise InvalidResult('上游缺少 gameID，无法确认 LOL')
    if str(data['gameID']) != '1':
        raise NonLOLResult(f"gameID={data['gameID']}，不是 LOL")
    result_id = int(result_id)
    if data.get('resultID') and int(data['resultID']) != result_id:
        raise InvalidResult('返回的 resultID 与请求的单局 ID 不一致')
    info = data.get('result_list')
    if not isinstance(info, dict) or not info:
        raise PendingResult('result_list 尚未生成')
    names = {side: info.get(f'{side}_name') for side in ('red', 'blue')}
    if any(not isinstance(name, str) or not name.strip() for name in names.values()):
        exception = SourceIncompleteResult if allow_incomplete else InvalidResult
        raise exception('详情缺少完整的双方队名')
    if names['red'] == names['blue']:
        raise InvalidResult('双方队名相同，无法形成正确自然键')
    results = {side: _winner(info.get(f'{side}_result'), f'{side}_result') for side in names}
    if sum(results.values()) != 1:
        raise PendingResult('双方胜负尚未确定')
    missing = []
    minutes = numeric(info.get('game_time_m'), 'game_time_m', integer=True, required=not allow_incomplete)
    seconds = numeric(info.get('game_time_s'), 'game_time_s', integer=True, required=not allow_incomplete)
    if seconds is not None and seconds >= 60:
        raise InvalidResult('game_time_s 必须小于 60')
    duration = minutes * 60 + seconds if minutes is not None and seconds is not None else None
    if not duration:
        if not allow_incomplete:
            raise PendingResult('单局时长尚未产生')
        duration = None
        missing.append('game_time')
    schedule = schedule or {}
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
    source_series = (data.get('max_mvp') or {}).get('match_id')
    series_id = schedule.get('series_id') or (int(source_series) if source_series else None)
    if source_series and schedule.get('series_id') and int(source_series) != int(schedule['series_id']):
        raise InvalidResult('赛程 series_id 与详情所属 BO 系列不一致')
    match = {
        'match_id': result_id, 'series_id': series_id,
        'tournament_id': schedule.get('tournament_id'), 'tournament_name': schedule.get('tournament_name'),
        'date': date, 'date_source': date_source, 'game_time': duration,
        'red_team_name': names['red'], 'blue_team_name': names['blue'],
        'win_team_name': next(names[side] for side in names if results[side] == 1),
        'mvp': mvp, 'source': 'scoregg', 'verified': True,
    }
    teams = []
    players = []
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
                exception = SourceIncompleteResult if allow_incomplete else InvalidResult
                raise exception(f'{prefix}name: 缺少选手，完整单局需要 10 位选手')
            team[f'player_{pos}_id'] = name
            player = {
                'match_id': result_id, 'date': date, 'name': name, 'pic': info.get(prefix + 'pic'),
                'hero': info.get(f'{side}_hero_{pos}_name'),
                'hero_lv': numeric(info.get(f'{side}_hero_{pos}_lv'), 'hero_lv', integer=True),
                'team_name': names[side], 'position': pos, 'game_time': duration,
                'result': str(results[side]),
            }
            for target, source in player_stats.items():
                key = prefix + source
                player[target] = numeric(
                    info.get(key), key, integer=target in player_ints,
                    required=target in ('kills', 'deaths', 'assists') and not allow_incomplete,
                    percentage=target in ('part', 'atk_p', 'def_p'),
                )
                if target in ('kills', 'deaths', 'assists') and player[target] is None:
                    missing.append(key)
            players.append(player)
        teams.append(team)
    normalized = {'matches': [match], 'teams': teams, 'players': players}
    if missing:
        normalized['source_incomplete'] = missing
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


def ingest_result(payload, result_id, schedule=None, run_id=None, allow_incomplete=False, replace_existing=False):
    try:
        data = normalize_result(payload, result_id, schedule, allow_incomplete)
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
        existing = db.session.query(Match).filter_by(match_id=result_id).first()
        preserve_nulls = (not replace_existing and existing is not None
                          and existing.source == 'scoregg' and existing.verified)
        if existing is not None and existing.date_source == 'schedule' and data['matches'][0]['date_source'] != 'schedule':
            data['matches'][0]['date'] = existing.date
            data['matches'][0]['date_source'] = 'schedule'
            for row in data['teams'] + data['players']:
                row['date'] = existing.date
        # 未核验旧值不能借本次 gameID 证据升为来源数据；首次核验按原始详情清除缺项。
        # 只有此前已核验的 ScoreGG 记录，才允许保留早前有来源依据的可选指标。
        bulk_upsert(Match, data['matches'], ['match_id'], preserve_nulls=preserve_nulls)
        bulk_upsert(Team, data['teams'], ['match_id', 'team_name'], preserve_nulls=preserve_nulls)
        bulk_upsert(Player, data['players'], ['match_id', 'team_name', 'position'], preserve_nulls=preserve_nulls)
        # 线上完整结果替换历史残缺/冲突多出来的自然键，现有正确记录仍原位更新。
        team_names = [team['team_name'] for team in data['teams']]
        db.session.query(Player).filter(Player.match_id == result_id, or_(
            ~Player.team_name.in_(team_names), ~Player.position.in_(list('abcde')),
        )).delete(synchronize_session=False)
        db.session.query(Team).filter(Team.match_id == result_id, ~Team.team_name.in_(team_names)).delete(synchronize_session=False)
        status = 'source_incomplete' if data.get('source_incomplete') else 'imported'
        error = ', '.join(data['source_incomplete']) if data.get('source_incomplete') else None
        finish_task(result_id, status, error, schedule=schedule, run_id=run_id)
        db.session.commit()
    except SQLAlchemyError as exc:
        return mark_failure(result_id, exc, schedule, run_id)
    return IngestOutcome(result_id, status, error)
