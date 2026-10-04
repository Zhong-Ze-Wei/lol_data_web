"""官网已归档单局基础统计；未知色方、位置和精确时长保持未知。"""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.services.ingestion import InvalidResult, numeric
from app.services.source_identity import source_player_id
from app.services.spider import SourceError, metadata_result_list


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def archived_metadata(schedule, archive):
    """缓存必须仍是本赛程已验证的真实 metadata 响应，不能冒充 CDN 详情。"""
    if not isinstance(archive, dict) or any(not archive.get(key) for key in ('raw_file', 'sha256', 'evidence_file')):
        raise SourceError('metadata 缺少完整原件/验证记录定位')
    encoded = Path(archive['raw_file']).read_bytes()
    if hashlib.sha256(encoded).hexdigest() != archive['sha256']:
        raise SourceError('metadata 原件 SHA 与持久依据不一致')
    receipt = json.loads(Path(archive['evidence_file']).read_bytes())
    metadata = receipt.get('metadata', {})
    if (receipt.get('source') != 'scoregg_match_metadata' or receipt.get('status') != 'validated'
            or receipt.get('series_id') != schedule['series_id']
            or receipt.get('raw_file') != archive['raw_file'] or receipt.get('sha256') != archive['sha256']
            or receipt.get('schedule_row_sha256') != canonical_sha(schedule.get('source_row'))
            or receipt.get('cdn', {}).get('http_status') != 404
            or receipt.get('cdn', {}).get('url') != f"https://img.scoregg.com/match/resultlist/{schedule['series_id']}.json"
            or metadata.get('url') != 'https://ho.scoregg.com/services/api_url.php'
            or metadata.get('method') != 'POST' or metadata.get('api_path') != '/services/match/match_info_new.php'):
        raise SourceError('metadata 来源记录/赛程原行/CDN404 依据不成立')
    payload = json.loads(encoded)
    metadata_result_list(payload, schedule)
    return payload


def normalize_metadata_snapshot(payload, result_id, schedule, archive):
    """只映射真实基础字段；A/B 是来源列表槽，绝不声明红蓝或角色。"""
    if archived_metadata(schedule, archive) != payload:
        raise InvalidResult('metadata 参数与实际归档不一致')
    data = payload['data']
    rows = [row for row in data['result_list'] if int(row['resultID']) == int(result_id)]
    if len(rows) != 1:
        raise InvalidResult('metadata 缺少唯一请求单局')
    row = rows[0]
    source_row = schedule['source_row']
    labels = {side: source_row.get(f'team_short_name_{side}') for side in ('a', 'b')}
    if any(not isinstance(label, str) or not label.strip() for label in labels.values()):
        raise InvalidResult('metadata 赛程缺少双方可靠名称')
    labels = {side: label.strip() for side, label in labels.items()}
    if labels['a'] == labels['b']:
        raise InvalidResult('metadata 双方名称重复')
    schedule_ids = {side: int(source_row[f'teamID_{side}']) for side in labels}
    mapping = {side: next(slot for slot in schedule_ids if schedule_ids[slot] == int(row[f'teamID_{side}']))
               for side in labels}
    names = {side: labels[mapping[side]] for side in labels}
    date = schedule['scheduled_at']
    teams, players, identifiers = [], [], set()
    for side in ('a', 'b'):
        team_id = int(row[f'teamID_{side}'])
        result = int(team_id == int(row['win_teamID']))
        team = {'match_id': int(result_id), 'date': date, 'team_name': names[side],
                'team_flag': row.get(f'team_{side}_image_thumb'), 'result': result, 'game_time': None}
        for target, source in (('kill', 'kills'), ('death', 'deaths'), ('assist', 'assists'),
                               ('money', 'money'), ('big_dargon', 'baron'), ('small_dargon', 'dragon')):
            team[target] = numeric(row.get(f'{source}_{side}'), f'{source}_{side}', integer=target != 'money')
        records = row.get(f'record_list_{side}')
        if not isinstance(records, list) or len(records) != 5:
            raise InvalidResult('metadata 需要每队五位真实来源选手，不能根据排列制造身份')
        for record in records:
            if not isinstance(record, dict):
                raise InvalidResult('metadata 选手结构无效')
            identifier = source_player_id(record.get('playerID'))
            if identifier is None or len(identifier) > 100 or identifier in identifiers:
                raise InvalidResult('metadata 选手 ID 缺少、重复或超出字段长度')
            if int(record.get('resultID', 0)) != int(result_id) or int(record.get('teamID', 0)) != team_id:
                raise InvalidResult('metadata 选手的单局/队伍身份矛盾')
            name = record.get('player_nickname')
            if not isinstance(name, str) or not name.strip():
                raise InvalidResult('metadata 选手缺少真实昵称')
            identifiers.add(identifier)
            player = {'match_id': int(result_id), 'date': date, 'name': name.strip(),
                      'source_player_id': identifier, 'pic': record.get('player_image_thumb'),
                      'team_name': names[side], 'position': None, 'game_time': None, 'result': str(result)}
            for field in ('kills', 'deaths', 'assists', 'mvp', 'beiguo'):
                value = numeric(record.get(field), field, integer=True)
                if field in ('mvp', 'beiguo') and value not in (None, 0, 1):
                    raise InvalidResult(f'metadata {field} 不是可靠 0/1 标志')
                player[field] = str(value) if field == 'beiguo' and value is not None else value
            players.append(player)
        for player_field, team_field in (('kills', 'kill'), ('deaths', 'death'), ('assists', 'assist')):
            values = [player[player_field] for player in players if player['team_name'] == names[side]]
            if all(value is not None for value in values) and team[team_field] is not None and sum(values) != team[team_field]:
                raise InvalidResult(f'metadata {player_field} 与战队汇总矛盾')
        teams.append(team)
    mvps = [player for player in players if player['mvp'] == 1 and player['result'] == '1']
    mvp = mvps[0]['name'] if len(mvps) == 1 else None
    for team in teams:
        team['mvp'] = mvp if team['result'] else None
    physical_names = {'blue': names['a'], 'red': names['b']}
    physical_ids = {'blue': int(row['teamID_a']), 'red': int(row['teamID_b'])}
    proof = {'policy_version': 2, 'source_kind': 'scoregg_metadata', 'source_policy': 'metadata_snapshot_v1',
             'side_basis': 'metadata_team_a_b', 'selected_source': 'schedule', 'status': 'verified',
             'reason': 'metadata_same_series_and_team_ids', 'selected_names': physical_names,
             'side_mapping': {'blue': mapping['a'], 'red': mapping['b']},
             'detail': {'names': {'blue': row.get('team_a_short_name'), 'red': row.get('team_b_short_name')},
                        'team_ids': physical_ids, 'series_id': int(data['matchID']),
                        'series_id_source': 'metadata.data.matchID', 'primary_series_id': None,
                        'auxiliary_series_id': None, 'canonical_data_sha256': canonical_sha(data),
                        'archive': {'raw_file': archive['raw_file'], 'sha256': archive['sha256']}},
             'schedule': {'names': labels, 'team_ids': schedule_ids, 'series_id': schedule['series_id'],
                          'canonical_row_sha256': canonical_sha(source_row), 'archive': schedule['source_archive'],
                          'more_team_list': source_row.get('more_team_list')},
             'metadata': {**archive, 'canonical_result_sha256': canonical_sha(row), 'source_row': source_row}}
    match = {'match_id': int(result_id), 'series_id': schedule['series_id'],
             'tournament_id': schedule['tournament_id'], 'tournament_name': schedule['tournament_name'],
             'date': date, 'date_source': 'schedule', 'game_time': None,
             'red_team_name': names['b'], 'blue_team_name': names['a'],
             'win_team_name': next(names[side] for side in names if int(row[f'teamID_{side}']) == int(row['win_teamID'])),
             'mvp': mvp, 'source': 'scoregg_metadata', 'verified': True, 'team_name_provenance': proof}
    missing = ['官网 metadata 仅提供基础统计；真实红蓝方、选手位置和完整秒数未记录，分均指标不可计算']
    return {'matches': [match], 'teams': teams, 'players': players, 'source_incomplete': missing}


def metadata_after_detail_404(error, result_id, schedule, raw_dir, run_id=None):
    """详情真实 404 时，复用已取得的官网基础来源；零新增 HTTP。"""
    from app import db
    from app.models.match import Match
    from app.models.sync import HistorySeries
    from app.services.ingestion import ingest_metadata_result
    from app.services.spider import _new_response_archive, history_schedule

    if error.status_code != 404 or error.url != f'https://img.scoregg.com/match/result/{result_id}.json':
        return None
    existing = db.session.query(Match).filter_by(match_id=result_id, source='scoregg', verified=True).first()
    if existing is not None:
        return None  # 高优先级详情不接受 metadata 覆盖；本次 HTTP 失败仍由 caller 如实记录。
    schedule = dict(schedule or {})
    archive = schedule.get('metadata_archive')
    series = db.session.get(HistorySeries, schedule['series_id']) if schedule.get('series_id') else None
    if series is not None and 'source_row' not in schedule:
        restored = series.schedule()
        for field in ('series_id', 'tournament_id', 'scheduled_at'):
            if schedule.get(field) is not None and schedule[field] != restored[field]:
                raise SourceError('metadata 缓存与当前任务声明的赛程不一致')
        schedule = restored
    if archive is None and series is not None and series.raw_file:
        path = Path(series.raw_file)
        directory = Path(raw_dir) / 'history' / 'resultlist-fallback' / str(series.series_id)
        if path.resolve().is_relative_to(directory.resolve()):
            for file in path.parent.glob('evidence-*.json'):
                receipt = json.loads(file.read_bytes())
                if receipt.get('status') == 'validated' and receipt.get('raw_file') == str(path):
                    archive = {'raw_file': str(path), 'sha256': series.raw_sha256, 'evidence_file': str(file)}
                    break
    if archive is None:
        match = db.session.query(Match).filter_by(match_id=result_id, source='scoregg_metadata', verified=True).first()
        if match is not None and match.team_name_provenance:
            proof = match.team_name_provenance
            archive = proof.get('metadata')
            if archive is not None:
                restored = history_schedule(archive['source_row'], match.tournament_id, match.tournament_name)
                for field in ('series_id', 'tournament_id', 'scheduled_at'):
                    if schedule.get(field) is not None and schedule[field] != restored[field]:
                        raise SourceError('metadata 缓存与当前任务声明的赛程不一致')
                schedule = {**restored, 'source_archive': proof['schedule']['archive']}
    if archive is None:
        return None
    payload = archived_metadata(schedule, archive)
    directory = Path(raw_dir) / 'history' / 'metadata-partials' / str(result_id) / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    evidence = {'source': 'scoregg_metadata', 'result_id': int(result_id), 'metadata_archive': archive,
                'detail': {'url': error.url, 'http_status': 404,
                           'response': _new_response_archive(directory / 'detail-404.body', error.response)}}
    path = directory / 'evidence.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
    outcome = ingest_metadata_result(payload, result_id, schedule, archive, run_id)
    return {**outcome.to_dict(), 'source': 'scoregg_metadata', 'detail_http_status': 404,
            'source_evidence': str(path), 'raw_file': archive['raw_file']}
