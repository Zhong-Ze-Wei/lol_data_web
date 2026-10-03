"""迁移无表头的旧 CSV；保留来源与问题报告，不推断未经核验的游戏类型。"""

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import SyncRun, SyncTask
from app.services.ingestion import InvalidResult, bulk_upsert, numeric


PLAYER_23_FIELDS = [
    'name', 'kda', 'kills', 'deaths', 'assists', 'part', 'atk', 'atk_p', 'atk_m',
    'def_', 'def_p', 'def_m', 'adc_m', 'money', 'money_M', 'wp_m', 'hits',
    'match_id', 'team_name', 'position', '_side', '_raw_time', 'result',
]
PLAYER_INTEGER_FIELDS = {'kills', 'deaths', 'assists', 'atk', 'def_', 'money', 'hits'}
PLAYER_FLOAT_FIELDS = {'kda', 'part', 'atk_p', 'atk_m', 'def_p', 'def_m', 'adc_m', 'money_M', 'wp_m'}


def parse_legacy_duration(value):
    text = str(value).strip()
    # 旧文件是分钟与两位秒的字符串拼接，例如 3410=34分10秒，950=9分50秒。
    if len(text) < 3 or not text.isdigit() or int(text[-2:]) >= 60:
        return None
    return int(text[:-2]) * 60 + int(text[-2:])


def _legacy_stat(value, field, issues, integer=False, percentage=False):
    try:
        return numeric(value, field, integer=integer, percentage=percentage)
    except InvalidResult as exc:
        issues.append({'field': field, 'raw_value': value, 'error': str(exc)})
        return None


def parse_player_row(row):
    if len(row) == 26:
        row = [value for index, value in enumerate(row) if index not in (6, 10, 15)]
    if len(row) != 23:
        raise InvalidResult(f'选手行需要 23 或 26 列，实际 {len(row)} 列')
    player = dict(zip(PLAYER_23_FIELDS, (value.strip() for value in row)))
    player['match_id'] = numeric(player['match_id'], 'match_id', integer=True, required=True)
    if player['match_id'] < 1:
        raise InvalidResult('比赛 ID 必须为正整数')
    if not player['name'] or not player['team_name']:
        raise InvalidResult('选手行缺少姓名或队名')
    if player['position'] not in 'abcde' or len(player['position']) != 1:
        raise InvalidResult(f"位置无效: {player['position']!r}")
    if player['_side'] not in ('red', 'blue'):
        raise InvalidResult(f"红蓝方无效: {player['_side']!r}")
    if player['result'] not in ('0', '1'):
        raise InvalidResult(f"胜负标志无效: {player['result']!r}")
    issues = []
    for field in PLAYER_INTEGER_FIELDS | PLAYER_FLOAT_FIELDS:
        player[field] = _legacy_stat(
            player[field], field, issues, integer=field in PLAYER_INTEGER_FIELDS,
            percentage=field in ('part', 'atk_p', 'def_p'),
        )
    player['game_time'] = parse_legacy_duration(player['_raw_time'])
    if player['game_time'] is None:
        issues.append({'field': 'game_time', 'raw_value': player['_raw_time'], 'error': '拼接时长无法可靠解码'})
    player['_issues'] = issues
    return player


def parse_team_row(row):
    if len(row) != 13:
        raise InvalidResult(f'队伍行需要 13 列，实际 {len(row)} 列')
    fields = ['match_id', 'team_name', 'result', '_date', 'mvp', '_raw_time',
              'small_dargon', 'big_dargon', 'tower', 'kill', 'death', 'assist', 'money']
    team = dict(zip(fields, (value.strip() for value in row)))
    team['match_id'] = numeric(team['match_id'], 'match_id', integer=True, required=True)
    if team['match_id'] < 1:
        raise InvalidResult('比赛 ID 必须为正整数')
    if not team['team_name']:
        raise InvalidResult('队伍行缺少队名')
    if team['result'] not in ('0', '1'):
        raise InvalidResult('队伍胜负标志必须为 0 或 1')
    team['result'] = int(team['result'])
    issues = []
    for field in ('small_dargon', 'big_dargon', 'tower', 'kill', 'death', 'assist', 'money'):
        team[field] = _legacy_stat(team[field], field, issues, integer=field != 'money')
    try:
        team['date'] = datetime.strptime(team['_date'], '%Y%m%d%H%M%S') if team['_date'] else None
    except ValueError:
        team['date'] = None
        issues.append({'field': 'date', 'raw_value': team['_date'], 'error': 'updated_at 日期无效'})
    team['game_time'] = parse_legacy_duration(team['_raw_time'])
    if team['game_time'] is None:
        issues.append({'field': 'game_time', 'raw_value': team['_raw_time'], 'error': '拼接时长无法可靠解码'})
    team['_issues'] = issues
    return team


def _business_row(row):
    return {key: value for key, value in row.items() if not key.startswith('_')}


class LegacyReport:
    def __init__(self, directory, run_id):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f'{run_id}.json'
        self.issues_path = directory / f'{run_id}.issues.jsonl'
        self.handle = self.issues_path.open('w', encoding='utf-8')
        self.counts = defaultdict(int)

    def issue(self, kind, **details):
        self.counts[kind] += 1
        self.handle.write(json.dumps({'kind': kind, **details}, ensure_ascii=False, default=str) + '\n')

    def close(self, summary):
        self.handle.close()
        summary['issues'] = dict(self.counts)
        summary['issues_file'] = str(self.issues_path)
        summary['report_file'] = str(self.path)
        self.path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        return summary


def import_legacy(data_dir, reports_dir=None, run_id=None, batch_size=250, force=False):
    data_dir = Path(data_dir).resolve()
    if not data_dir.is_dir():
        raise ValueError(f'旧数据目录不存在: {data_dir}')
    if batch_size < 1:
        raise ValueError('batch_size 必须为正数')
    files = sorted(data_dir.rglob('*.csv'))
    fingerprints = {path: {'file': str(path.relative_to(data_dir)),
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                          'bytes': path.stat().st_size} for path in files}
    run_id = run_id or f'legacy-{uuid4()}'
    report = LegacyReport(reports_dir or data_dir.parent / 'reports', run_id)
    summary = {'run_id': run_id, 'source': 'legacy', 'verified': False,
               'files': [], 'imported_matches': 0, 'imported_teams': 0, 'imported_players': 0,
               'duplicate_rows': 0, 'preserved_verified_matches': 0, 'excluded_non_lol_matches': 0}
    stores = {'player': {}, 'team': {}}
    conflicts = {'player': set(), 'team': set()}
    hashes = {}
    try:
        # 同一数据库中成功导入过且源文件未变，只读 hash 即可复跑；--force 可显式重建。
        previous = db.session.query(SyncRun).filter_by(command='import-legacy', status='completed').order_by(SyncRun.started_at.desc()).first()
        if previous is not None and previous.details and not force:
            cached = json.loads(previous.details).get('legacy')
            current = {info['file']: info['sha256'] for info in fingerprints.values()}
            prior = {info['file']: info['sha256'] for info in cached['files']} if cached else None
            existing = db.session.query(Match).count() + db.session.query(SyncTask).filter_by(status='skipped').count()
            if current == prior and cached.get('dataset_matches', 0) > 0 and existing >= cached['dataset_matches']:
                summary.update(status='unchanged', files=list(fingerprints.values()),
                               dataset_matches=cached['dataset_matches'], previous_report=cached.get('report_file'),
                               previous_issues_file=cached.get('previous_issues_file') or cached.get('issues_file'), message='文件 hash 未变化，已导入记录不重复写入；--force 可强制重新解析')
                return report.close(summary)
        for path in files:
            # 同目录里新抓的 JSON 与 processed 特征表不是 legacy 原始输入。
            kind = 'player' if path.name.startswith('player_data') else 'team' if path.name.startswith('team_data') else None
            info = dict(fingerprints[path])
            digest = info['sha256']
            summary['files'].append(info)
            if kind is None:
                info['status'] = 'archived_only'
                if path.name == 'all.csv':
                    report.issue('no_match_id', file=info['file'], reason='all.csv 无比赛 ID，不导入数据库')
                continue
            if digest in hashes:
                info.update(status='identical_file', duplicate_of=hashes[digest])
                continue
            hashes[digest] = info['file']
            info['status'] = 'parsed'
            info['rows'] = 0
            with path.open(encoding='utf-8-sig', newline='') as handle:
                for line, raw in enumerate(csv.reader(handle), 1):
                    info['rows'] += 1
                    provenance = {'file': info['file'], 'line': line}
                    try:
                        row = parse_player_row(raw) if kind == 'player' else parse_team_row(raw)
                    except InvalidResult as exc:
                        report.issue('invalid_row', **provenance, error=str(exc), raw=raw)
                        continue
                    for issue in row['_issues']:
                        report.issue('invalid_field', **provenance, match_id=row['match_id'], **issue)
                    key = (row['match_id'], row['team_name'], row['position']) if kind == 'player' else (row['match_id'], row['team_name'])
                    business = _business_row(row)
                    # side 虽不存业务表，必须参与冲突判定，不能悄悄更改红蓝归属。
                    comparable = {**business, '_side': row.get('_side')}
                    previous = stores[kind].get(key)
                    if previous is None:
                        stores[kind][key] = (row, provenance, comparable)
                    elif previous[2] == comparable:
                        summary['duplicate_rows'] += 1
                    else:
                        if key not in conflicts[kind]:
                            report.issue('conflicting_natural_key', entity=kind, key=key,
                                         first=previous[1], other=provenance,
                                         variants=[previous[2], comparable], action='不选取任一冲突记录')
                        conflicts[kind].add(key)
        grouped = defaultdict(lambda: {'teams': [], 'players': []})
        for kind, store in stores.items():
            for key, (row, provenance, _) in store.items():
                if key not in conflicts[kind]:
                    grouped[row['match_id']]['players' if kind == 'player' else 'teams'].append(row)
        verified_ids = set(db.session.execute(select(Match.match_id).where(Match.verified.is_(True))).scalars())
        excluded_ids = set(db.session.execute(select(SyncTask.result_id).where(SyncTask.status == 'skipped', SyncTask.result_id.is_not(None))).scalars())
        summary['dataset_matches'] = len(grouped)
        batches = []
        for match_id, records in grouped.items():
            if match_id in verified_ids:
                summary['preserved_verified_matches'] += 1
                continue
            if match_id in excluded_ids:
                summary['excluded_non_lol_matches'] += 1
                report.issue('excluded_non_lol', match_id=match_id, reason='已有 gameID 核验的非 LOL 审计，不重新导入')
                continue
            teams = records['teams']
            players = records['players']
            report.issue('unverified_game', match_id=match_id, reason='旧 CSV 无 gameID；不能确认都是 LOL')
            if len(teams) != 2:
                report.issue('missing_sides', match_id=match_id, team_count=len(teams))
            if len(players) != 10:
                report.issue('missing_players', match_id=match_id, player_count=len(players))
            side_names = {side: {p['team_name'] for p in players if p['_side'] == side} for side in ('red', 'blue')}
            if any(len(names) != 1 for names in side_names.values()):
                report.issue('inconsistent_sides', match_id=match_id, side_team_names={side: sorted(names) for side, names in side_names.items()})
            if {p['team_name'] for p in players} - {t['team_name'] for t in teams}:
                report.issue('players_without_team_record', match_id=match_id,
                             names=sorted({p['team_name'] for p in players} - {t['team_name'] for t in teams}))
            dates = {t['date'] for t in teams if t['date'] is not None}
            durations = {r['game_time'] for r in teams + players if r['game_time'] is not None}
            date = next(iter(dates)) if len(dates) == 1 else None
            duration = next(iter(durations)) if len(durations) == 1 else None
            if len(dates) > 1 or len(durations) > 1:
                report.issue('conflicting_match_fields', match_id=match_id,
                             dates=sorted(str(d) for d in dates), durations=sorted(durations))
            winners = {t['team_name'] for t in teams if t['result'] == 1}
            mvp_names = {t['mvp'] for t in teams if t['mvp']}
            match = {
                'match_id': match_id, 'series_id': None, 'tournament_id': None, 'tournament_name': None,
                'date': date, 'date_source': 'updated_at' if date else 'unknown', 'game_time': duration,
                'red_team_name': next(iter(side_names['red'])) if len(side_names['red']) == 1 else None,
                'blue_team_name': next(iter(side_names['blue'])) if len(side_names['blue']) == 1 else None,
                'win_team_name': next(iter(winners)) if len(winners) == 1 else None,
                'mvp': next(iter(mvp_names)) if len(mvp_names) == 1 else None,
                'source': 'legacy', 'verified': False,
            }
            if match['red_team_name'] is None or match['blue_team_name'] is None:
                report.issue('unknown_side_assignment', match_id=match_id, reason='CSV 缺少可靠双方位置，不猜测红蓝队名')
            clean_teams = [_business_row(t) for t in teams]
            clean_players = [{**_business_row(p), 'date': date} for p in players]
            batches.append((match, clean_teams, clean_players))
            if len(batches) >= batch_size:
                _write_batch(batches, summary)
                batches = []
        _write_batch(batches, summary)
    except Exception:
        # 边界处回滚并保存已解析报告，避免批次错误后给出成功结论。
        db.session.rollback()
        summary['status'] = 'failed'
        report.close(summary)
        raise
    summary['status'] = 'completed'
    return report.close(summary)


def _write_batch(batch, summary):
    if not batch:
        return
    matches = [item[0] for item in batch]
    teams = [row for item in batch for row in item[1]]
    players = [row for item in batch for row in item[2]]
    bulk_upsert(Match, matches, ['match_id'])
    bulk_upsert(Team, teams, ['match_id', 'team_name'])
    bulk_upsert(Player, players, ['match_id', 'team_name', 'position'])
    db.session.commit()
    summary['imported_matches'] += len(matches)
    summary['imported_teams'] += len(teams)
    summary['imported_players'] += len(players)
