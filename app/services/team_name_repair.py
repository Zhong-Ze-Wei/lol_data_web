"""显式单局范围的队名修复：只更新名称和队名证据，不重放指标或身份。"""

import copy
import hashlib
import json
import math
import sqlite3
from contextlib import closing, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.services.ingestion import normalize_result
from app.services.team_names import resolve_team_names
from scripts.migrate_team_name_provenance import backup_before_migration, migration_lock


class TeamNameRepairError(ValueError):
    pass


def _json_file(path):
    encoded = Path(path).read_bytes()
    return json.loads(encoded), hashlib.sha256(encoded).hexdigest()


def _row(connection, table, column, value):
    rows = connection.execute(f'SELECT * FROM {table} WHERE {column}=?', (value,)).fetchall()
    if len(rows) != 1:
        raise TeamNameRepairError(f'{table} 身份记录不是唯一一条')
    return dict(rows[0])


def _game(connection, result_id):
    return {'matches': [_row(connection, 'matches', 'match_id', result_id)],
            **{table: [dict(row) for row in connection.execute(
                f'SELECT * FROM {table} WHERE match_id=? ORDER BY id', (result_id,))]
               for table in ('teams', 'players')}}


def _schedule(connection, match):
    series = _row(connection, 'history_series', 'series_id', match['series_id'])
    stage = _row(connection, 'history_stages', 'id', series['stage_id'])
    if series['tournament_id'] != stage['tournament_id']:
        raise TeamNameRepairError('系列与阶段的赛事身份不一致')
    row = json.loads(series['source_json'])
    pair = (series['schedule_raw_file'], series['schedule_raw_sha256'])
    if pair == (None, None):
        pair = (stage['raw_file'], stage['raw_sha256'])
    if not all(pair):
        raise TeamNameRepairError('没有可复核的赛程原件版本绑定')
    rows, digest = _json_file(pair[0])
    if digest != pair[1] or not isinstance(rows, list) or sum(item == row for item in rows) != 1:
        raise TeamNameRepairError('赛程原件 SHA 或唯一原行不匹配')
    schedule = {'series_id': series['series_id'], 'tournament_id': series['tournament_id'],
                'scheduled_at': series['scheduled_at'], 'source_row': row,
                'source_archive': {'raw_file': pair[0], 'sha256': pair[1]}}
    return schedule, {'series': series, 'stage': stage}


def _old_color_mapping(match, data, detail_names, proof):
    old = {side: match[f'{side}_team_name'] for side in ('red', 'blue')}
    if any(not isinstance(name, str) or not name.strip() for name in old.values()) or len(set(old.values())) != 2:
        raise TeamNameRepairError('现有红蓝名称缺失或重复，不能猜测队伍身份')
    previous = json.loads(match['team_name_provenance']) if match['team_name_provenance'] else None
    current_ids = proof['detail']['team_ids']
    if isinstance(previous, dict):
        prior = previous.get('detail') or {}
        if not isinstance(prior, dict):
            raise TeamNameRepairError('已有详情来源证明结构无效')
        prior_ids = prior.get('team_ids') or {}
        if not isinstance(prior_ids, dict):
            raise TeamNameRepairError('已有双方 ID 来源证明结构无效')
        if any(type(value) is int and value > 0 and value not in current_ids.values()
               for value in prior_ids.values()):
            raise TeamNameRepairError('已有来源证明的双方 ID 与当前详情冲突')
        known_pair = (set(prior_ids) == {'red', 'blue'}
                      and all(type(value) is int and value > 0 for value in prior_ids.values())
                      and len(set(prior_ids.values())) == 2)
        if known_pair and (prior.get('series_id') is not None and prior['series_id'] != match['series_id']
                           or set(prior_ids.values()) != set(current_ids.values())):
            raise TeamNameRepairError('已有来源证明的 BO/双方 ID 与当前详情冲突')
        if previous.get('selected_source') == 'schedule' and previous.get('status') == 'verified':
            if previous.get('selected_names') != old or not known_pair:
                raise TeamNameRepairError('此前已核验来源不能证明现有队名与双方 ID')
            _, checked = resolve_team_names(data, {}, detail_names, previous=previous)
            if checked['selected_source'] != 'schedule':
                raise TeamNameRepairError('此前队名来源不能重新证明相同 BO 与双方 ID')
            # 详情名称可能可变；已有数值行属于此前 ID，不能被新红蓝颜色重排。
            return old, {side: next(color for color in current_ids if current_ids[color] == identifier)
                         for side, identifier in prior_ids.items()}
    if old == detail_names:
        return old, {'red': 'red', 'blue': 'blue'}
    raise TeamNameRepairError('现有队名既不对应详情，也没有同 ID 已核验来源证明')


def _correct_proof(previous, proof, source_row, payload):
    if not isinstance(previous, dict):
        return False
    if (not all(previous.get(key) == proof[key] for key in ('selected_source', 'status', 'selected_names'))
            or previous.get('side_mapping') != proof['side_mapping']):
        return False
    for name in ('detail', 'schedule'):
        old = previous.get(name)
        if not isinstance(old, dict) or {key: value for key, value in old.items() if key != 'archive'} != {
                key: value for key, value in proof[name].items() if key != 'archive'}:
            return False
        archive = old.get('archive')
        if not isinstance(archive, dict):
            return False
        try:
            content, digest = _json_file(archive['raw_file'])
        except (OSError, ValueError, KeyError):
            return False
        if digest != archive.get('sha256'):
            return False
        if name == 'detail':
            if (not isinstance(content, dict) or content.get('code', 200) not in (200, '200')
                    or content.get('data') != payload['data']):
                return False
        elif not isinstance(content, list) or sum(row == source_row for row in content) != 1:
            return False
    return True


def _audit_game(connection, result_id, raw_dir):
    before = _game(connection, result_id)
    match = before['matches'][0]
    if match['source'] != 'scoregg' or match['verified'] != 1:
        raise TeamNameRepairError('只接受已核验 ScoreGG 单局')
    schedule, source = _schedule(connection, match)
    raw = raw_dir / 'scoregg' / f'{result_id}.json'
    payload, digest = _json_file(raw)
    schedule['detail_archive'] = {'raw_file': str(raw), 'sha256': digest}
    # 完整运行现有规范仅验证公开单局，不把规范化的指标/名单重新写入数据库。
    normalized = normalize_result(payload, result_id, schedule, allow_incomplete=True)
    proof = normalized['matches'][0]['team_name_provenance']
    if proof['selected_source'] != 'schedule' or proof['status'] != 'verified':
        raise TeamNameRepairError(f"双方 BO/teamID 未通过队名规则：{proof['reason']}")
    detail_names = proof['detail']['names']
    old, mapping = _old_color_mapping(match, payload['data'], detail_names, proof)
    if len(before['teams']) != 2 or {row['team_name'] for row in before['teams']} != set(old.values()):
        raise TeamNameRepairError('现有 Team 不是恰好双方两条，不能删除或猜测映射')
    keys = set()
    for player in before['players']:
        key = (player['team_name'], player['position'])
        if player['team_name'] not in old.values() or player['position'] not in tuple('abcde') or key in keys:
            raise TeamNameRepairError('存在第三方/NULL队名、未知位置或重复 Player 自然键')
        keys.add(key)
    winner = match['win_team_name']
    if winner not in (None, '') and winner not in old.values():
        raise TeamNameRepairError('已有胜方不属于已证明的旧红蓝双方')
    names = proof['selected_names']
    rename = {old[side]: names[mapping[side]] for side in old}
    previous = json.loads(match['team_name_provenance']) if match['team_name_provenance'] else None
    noop = (old == names and all(name == target for name, target in rename.items())
            and _correct_proof(previous, proof, schedule['source_row'], payload))
    after = copy.deepcopy(before)
    if not noop:
        after['matches'][0].update(red_team_name=names['red'], blue_team_name=names['blue'],
                                   win_team_name=winner if winner in (None, '') else rename[winner],
                                   team_name_provenance=json.dumps(proof, ensure_ascii=False, sort_keys=True))
        for table in ('teams', 'players'):
            for row in after[table]:
                row['team_name'] = rename[row['team_name']]
    return {'result_id': result_id, 'status': 'noop' if noop else 'ready', 'before': before, 'after': after,
            'schedule': schedule, 'source_state': source, 'rename': rename, 'team_name_provenance': proof}


def _check_sources(connection, item):
    if _game(connection, item['result_id']) != item['before']:
        raise TeamNameRepairError('审计后单局来源、身份、名称或业务字段已改变')
    source = item['source_state']
    if (_row(connection, 'history_series', 'series_id', source['series']['series_id']) != source['series']
            or _row(connection, 'history_stages', 'id', source['stage']['id']) != source['stage']):
        raise TeamNameRepairError('审计后持久赛程原行、阶段或版本绑定改变')
    for name in ('detail_archive', 'source_archive'):
        archive = item['schedule'][name]
        try:
            _, digest = _json_file(archive['raw_file'])
        except (OSError, ValueError) as error:
            raise TeamNameRepairError('审计后来源原件无法继续复核') from error
        if digest != archive['sha256']:
            raise TeamNameRepairError('审计后来源原件 SHA 改变')


def _apply_game(connection, item):
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        _check_sources(connection, item)
        prefix = '__team_name_repair_' + uuid4().hex + '_'
        for index, (old, target) in enumerate(item['rename'].items()):
            if old == target:
                continue
            for table in ('teams', 'players'):
                for row in item['before'][table]:
                    if row['team_name'] == old:
                        connection.execute(f'UPDATE {table} SET team_name=? WHERE id=? AND match_id=?',
                                           (prefix + str(index), row['id'], item['result_id']))
        for table in ('teams', 'players'):
            for row in item['after'][table]:
                before = next(value for value in item['before'][table] if value['id'] == row['id'])
                if before['team_name'] != row['team_name']:
                    connection.execute(f'UPDATE {table} SET team_name=? WHERE id=? AND match_id=?',
                                       (row['team_name'], row['id'], item['result_id']))
        match = item['after']['matches'][0]
        connection.execute('UPDATE matches SET red_team_name=?,blue_team_name=?,win_team_name=?,team_name_provenance=? WHERE id=? AND match_id=?',
                           (match['red_team_name'], match['blue_team_name'], match['win_team_name'],
                            match['team_name_provenance'], match['id'], item['result_id']))
        if _game(connection, item['result_id']) != item['after']:
            raise TeamNameRepairError('更新后全行不符合仅名称/证据变更计划，已回滚')


def _write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def repair_team_names(database, raw_dir, reports_dir, *, result_ids, apply=False, wait_seconds=0):
    if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 60:
        raise TeamNameRepairError('--wait-seconds 必须在 0–60 秒之间')
    if not isinstance(result_ids, (list, tuple)) or not result_ids or any(type(value) is not int or value <= 0 for value in result_ids):
        raise TeamNameRepairError('必须显式提供非空正整数单局 ID 列表，不接受 all、布尔值或新队名')
    database, raw_dir, reports_dir = (Path(value).resolve() for value in (database, raw_dir, reports_dir))
    if not database.is_file() or not raw_dir.is_dir():
        raise TeamNameRepairError('database 和 raw-dir 必须已存在')
    with database.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\x00':
            raise TeamNameRepairError('目标不是 SQLite 数据库')
    report_id = str(uuid4())
    path = reports_dir / f'team-name-repair-{report_id}.json'
    report = {'repair_id': report_id, 'mode': 'apply' if apply else 'audit', 'database': str(database),
              'started_at': datetime.now(timezone.utc).isoformat(), 'request_count': 0, 'records': [],
              'checked': 0, 'changed': 0, 'noop': 0, 'blocked': 0, 'applied': 0, 'failed': 0,
              'report_file': str(path)}
    with migration_lock(database, wait_seconds) if apply else nullcontext():
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            for result_id in sorted(set(result_ids)):
                report['checked'] += 1
                try:
                    item = _audit_game(connection, result_id, raw_dir)
                except (OSError, ValueError, TypeError, KeyError, sqlite3.DatabaseError) as error:
                    item = {'result_id': result_id, 'status': 'blocked', 'error': str(error)}
                report['records'].append(item)
                if item['status'] == 'ready':
                    report['changed'] += 1
                else:
                    report[item['status']] += 1
            connection.rollback()
        _write_report(path, report)
        ready = [item for item in report['records'] if item['status'] == 'ready']
        if apply and ready:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
                backup = backup_before_migration(connection, database)
            backup_path = Path(backup['file'])
            destination = backup_path.with_name(backup_path.name.replace('schema-team-name-provenance-', 'repair-team-names-', 1))
            backup_path.replace(destination)
            report['backup'] = {**backup, 'file': str(destination)}
            journal = path.with_suffix('.jsonl')
            report['journal_file'] = str(journal)
            _write_report(path, report)
            with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute('PRAGMA foreign_keys=ON')
                for item in ready:
                    try:
                        _apply_game(connection, item)
                        item['status'] = 'applied'
                        report['applied'] += 1
                    except TeamNameRepairError as error:
                        item.update(status='blocked', error=str(error))
                        report['blocked'] += 1
                    except (OSError, ValueError, TypeError, sqlite3.DatabaseError) as error:
                        item.update(status='failed', error=str(error))
                        report['failed'] += 1
                    with journal.open('a', encoding='utf-8') as output:
                        output.write(json.dumps({'result_id': item['result_id'], 'status': item['status'],
                                                 'error': item.get('error')}, ensure_ascii=False) + '\n')
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        _write_report(path, report)
    return report
