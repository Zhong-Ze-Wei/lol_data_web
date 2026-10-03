"""可恢复的全历史目录、阶段与单局清单；覆盖率不以旧 CSV 更新时间计年。"""

import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import String, func, or_

from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import HistoryTournament, HistoryStage, HistorySeries, SyncTask, utc_now
from app.services.ingestion import (
    get_task, has_finished_lol_evidence, ingest_result, mark_failure, normalize_result, start_task,
)
from app.services.spider import (
    BudgetExceeded, SourceError, SourceHTTPError, history_schedule, parse_tournament_page,
    result_ids_from_list, tournament_catalog, tournament_stages,
)
from app.services.team_names import resolve_team_names


def _archive(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    temporary = path.with_suffix(path.suffix + f'.{os.getpid()}.tmp')
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return str(path), hashlib.sha256(encoded).hexdigest()


def _date(value):
    if value in (None, '', '0000-00-00'):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError) as exc:
        raise SourceError(f'赛事目录日期无效: {value!r}') from exc


def _finish(entity, status, error=None, raw=None):
    entity.status = status
    entity.last_error = str(error) if error else None
    entity.updated_at = utc_now()
    if status == 'failed':
        entity.failure_count = (entity.failure_count or 0) + 1
        entity.next_retry_at = utc_now() + timedelta(minutes=min(1440, 2 ** entity.failure_count))
    elif status == 'pending':
        entity.failure_count = 0
        entity.next_retry_at = utc_now() + timedelta(days=1)
    else:
        entity.failure_count = 0
        entity.next_retry_at = None
        entity.discovered_at = utc_now()
    if raw:
        entity.raw_file, entity.raw_sha256 = raw
    db.session.commit()


def _start(entity):
    entity.status = 'running'
    entity.attempts = (entity.attempts or 0) + 1
    db.session.commit()


def _ready(query, model, max_attempts, include_pending=False):
    return query.filter(
        model.status.in_(['queued', 'failed', 'pending'] if include_pending else ['queued', 'failed']), model.failure_count < max_attempts,
        or_(model.next_retry_at.is_(None), model.next_retry_at <= utc_now()),
    )


def _pending(schedule, now):
    return (str(schedule.get('status')) == '0'
            or (schedule.get('scheduled_at') is not None and schedule['scheduled_at'] > now)
            or schedule.get('is_publist') == 0)


def _seed_catalog(client, raw_dir, refresh=False):
    checked_at = utc_now()
    newest = db.session.query(func.max(HistoryTournament.last_seen_at)).scalar()
    if newest is not None and not refresh and newest > checked_at - timedelta(hours=24):
        return 0
    page = parse_tournament_page(client.get('https://www.scoregg.com/match_pc?tournamentID=1007').text)
    rows = tournament_catalog(page)
    _archive(raw_dir / 'history' / 'catalog.json', page)
    for row in rows:
        tid = int(row['tournamentID'])
        source = json.dumps(row, ensure_ascii=False, sort_keys=True)
        tour = db.session.get(HistoryTournament, tid)
        if tour is None:
            tour = HistoryTournament(tournament_id=tid, name=row['name'])
            db.session.add(tour)
        elif refresh or source != tour.source_json:
            tour.status = 'queued'
            tour.next_retry_at = None
            if refresh:
                for stage in db.session.query(HistoryStage).filter_by(tournament_id=tid).all():
                    stage.status, stage.next_retry_at = 'queued', None
                for series in db.session.query(HistorySeries).filter_by(tournament_id=tid).all():
                    series.status, series.next_retry_at = 'queued', None
        tour.name = row['name']
        tour.start_date, tour.end_date = _date(row.get('start_date')), _date(row.get('end_date'))
        tour.source_json = source
        tour.last_seen_at = checked_at
    db.session.commit()
    return len(rows)


def _discover_tournament(client, tour, raw_dir, now):
    previously_discovered = tour.discovered_at is not None
    _start(tour)
    rounds = client.get_json(f'https://img.scoregg.com/tr/{tour.tournament_id}.json')
    entries = tournament_stages(rounds, tour.tournament_id)
    raw = _archive(raw_dir / 'history' / 'tournaments' / f'{tour.tournament_id}.json', rounds)
    for entry in entries:
        stage = db.session.query(HistoryStage).filter_by(tournament_id=tour.tournament_id,
                                                       cache_key=entry['cache_key']).first()
        source = json.dumps(entry['source'], ensure_ascii=False, sort_keys=True)
        if stage is None:
            stage = HistoryStage(tournament_id=tour.tournament_id, cache_key=entry['cache_key'],
                                 parent_round_id=entry['parent_round_id'])
            db.session.add(stage)
        elif previously_discovered or source != stage.source_json:
            stage.status, stage.next_retry_at = 'queued', None
        stage.name, stage.source_json = entry['name'], source
    tour.stage_count = db.session.query(HistoryStage).filter_by(tournament_id=tour.tournament_id).count()
    _finish(tour, 'discovered', raw=raw)
    if tour.end_date is not None and tour.end_date >= now.date():
        tour.next_retry_at = utc_now() + timedelta(days=1)
        db.session.commit()


def _stage_unpublished(client, stage, error, raw_dir):
    source = json.loads(stage.source_json)
    if error.status_code != 404 or not stage.cache_key.startswith('p_') or str(source.get('is_now_week')) == '1':
        return False
    page = parse_tournament_page(client.get(f'https://www.scoregg.com/match_pc?tournamentID={stage.tournament_id}').text)
    _archive(raw_dir / 'history' / 'tournament_pages' / f'{stage.tournament_id}.json', page)
    published = page.get('week_player_select_list')
    if not isinstance(published, list):
        raise SourceError('官网缺少已发布阶段列表，不能将 404 判为待发布')
    stats = page.get('statistics') or {}
    if str(stats.get('game_count', '')).isdigit():
        db.session.get(HistoryTournament, stage.tournament_id).expected_game_count = int(stats['game_count'])
    return str(stage.parent_round_id) not in {str(item['id']) for item in published}


def _queue_parent_stage(stage):
    """子阶段404时保留失败，另以已知父ID尝试官方总赛程入口。"""
    key = f'p_{stage.parent_round_id}'
    parent = db.session.query(HistoryStage).filter_by(tournament_id=stage.tournament_id, cache_key=key).first()
    if parent is not None:
        return
    source = json.loads(stage.source_json)
    parent = HistoryStage(tournament_id=stage.tournament_id, cache_key=key,
                          parent_round_id=stage.parent_round_id, name=source.get('name'),
                          source_json=stage.source_json, status='queued')
    db.session.add(parent)
    db.session.flush()
    tour = db.session.get(HistoryTournament, stage.tournament_id)
    tour.stage_count = db.session.query(HistoryStage).filter_by(tournament_id=stage.tournament_id).count()
    # 调用方会回滚本次失败；独立持久化父游标才能在预算退出后继续。
    db.session.commit()


def _archive_stage_payload(stage, raw_dir, rows, *, failed=False):
    """已被战报引用的成功原件不覆盖；更正和失败响应各自留档。"""
    directory = raw_dir / 'history' / 'stages' / str(stage.tournament_id)
    ordinary = directory / f'{stage.cache_key}.json'
    if failed:
        failed_path = directory / 'failed-attempts' / f'{stage.cache_key}-{uuid4().hex}.json'
        raw = _archive(failed_path, rows)
        if not stage.raw_file:
            # 首轮失败的常规原件入口沿用旧行为，此时没有成功来源绑定。
            _archive(ordinary, rows)
        return raw
    if not stage.raw_file:
        return _archive(ordinary, rows)
    encoded = json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest()
    previous = Path(stage.raw_file)
    if stage.raw_sha256 == digest and previous.is_file() and hashlib.sha256(previous.read_bytes()).hexdigest() == digest:
        return stage.raw_file, digest
    versioned = directory / f'{stage.cache_key}-{digest}.json'
    if versioned.is_file() and hashlib.sha256(versioned.read_bytes()).hexdigest() == digest:
        return str(versioned), digest
    return _archive(versioned, rows)


def _bind_legacy_stage_archives(stage):
    """首次新版刷新前，只按当前旧文件的真实 SHA/唯一原行补迁移空绑定。"""
    series_rows = db.session.query(HistorySeries).filter_by(stage_id=stage.id,
                                                           schedule_raw_file=None, schedule_raw_sha256=None).all()
    if not series_rows or not stage.raw_file or not stage.raw_sha256:
        return
    try:
        encoded = Path(stage.raw_file).read_bytes()
        rows = json.loads(encoded)
    except (OSError, ValueError):
        return
    if hashlib.sha256(encoded).hexdigest() != stage.raw_sha256 or not isinstance(rows, list):
        return
    row_counts = Counter(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')) for row in rows)
    for series in series_rows:
        if series.source_json is None:
            continue
        try:
            row = json.loads(series.source_json)
        except ValueError:
            continue
        if isinstance(row, dict) and row_counts[json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'))] == 1:
            series.schedule_raw_file, series.schedule_raw_sha256 = stage.raw_file, stage.raw_sha256


def _discover_stage(client, stage, raw_dir, now):
    _start(stage)
    try:
        rows = client.get_json(f'https://img.scoregg.com/tr_round/{stage.cache_key}.json')
    except SourceHTTPError as exc:
        if exc.status_code == 404 and not stage.cache_key.startswith('p_'):
            _queue_parent_stage(stage)
        if _stage_unpublished(client, stage, exc, raw_dir):
            _finish(stage, 'pending', '非当前父阶段且官网统计列表没有发布此阶段；保留 HTTP404 依据')
            return
        raise
    tour = db.session.get(HistoryTournament, stage.tournament_id)
    # 先完成全阶段校验，再提交；一个错误不能让半个阶段被标成发现完成。
    seen = set()
    try:
        if not isinstance(rows, list):
            raise SourceError(f'stage {stage.cache_key}: 赛程结构不是列表')
        schedules = [(row, history_schedule(row, tour.tournament_id, tour.name)) for row in rows]
        for row, schedule in schedules:
            sid = schedule['series_id']
            if sid in seen:
                raise SourceError(f'stage {stage.cache_key}: 重复 series_id={sid}')
            seen.add(sid)
            series = db.session.get(HistorySeries, sid)
            if series is not None and series.tournament_id != tour.tournament_id:
                raise SourceError(f'series {sid}: 同一系列出现在两个赛事，保留冲突以人工核对')
            for field in ('team_a_win', 'team_b_win'):
                if row.get(field) not in (None, ''):
                    int(row[field])
    except (SourceError, TypeError, ValueError):
        _archive_stage_payload(stage, raw_dir, rows, failed=True)
        raise
    raw = _archive_stage_payload(stage, raw_dir, rows)
    _bind_legacy_stage_archives(stage)
    stage.raw_file, stage.raw_sha256 = raw
    for row, schedule in schedules:
        sid = schedule['series_id']
        series = db.session.get(HistorySeries, sid)
        if series is None:
            series = HistorySeries(series_id=sid, tournament_id=tour.tournament_id, stage_id=stage.id)
            db.session.add(series)
        source_changed = series.source_json is not None and json.loads(series.source_json) != row
        if source_changed or series.source_json is None:
            series.stage_id = stage.id
        series.scheduled_at = schedule['scheduled_at']
        series.source_status, series.is_publist = schedule['status'], schedule['is_publist']
        for field, value in (('team_a_score', row.get('team_a_win')), ('team_b_score', row.get('team_b_win'))):
            setattr(series, field, int(value) if value not in (None, '') else None)
        series.source_json = json.dumps(row, ensure_ascii=False)
        series.schedule_raw_file, series.schedule_raw_sha256 = raw
        if _pending(schedule, now):
            series.status = 'pending'
            series.next_retry_at = utc_now() + timedelta(days=1)
        elif series.status == 'pending' or series.status is None or (source_changed and series.status == 'discovered'):
            series.status, series.next_retry_at = 'queued', None
        if series.status == 'discovered' or source_changed:
            # 赛程被更正时无需重下载所有原始战报，但需要幂等回填业务日期/赛事信息。
            _queue_series_results(series, raw_dir)
    stage.series_count = len(seen)
    _finish(stage, 'discovered', raw=raw)


def _structure_complete(match):
    if match is None or not match.verified or match.game_time is None or match.game_time <= 1:
        return False
    players = db.session.query(func.count(Player.id)).filter_by(match_id=match.match_id).scalar()
    teams = db.session.query(func.count(Team.id)).filter_by(match_id=match.match_id).scalar()
    return players == 10 and teams == 2


def _cached_team_names_changed(match, schedule, raw):
    """只有本地详情与赛程 ID/BO 匹配才重排名称；候选文字差异不足为证。"""
    if match is None or not match.verified or not raw.is_file():
        return False
    try:
        payload = json.loads(raw.read_bytes())
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict) or payload.get('code', 200) not in (200, '200'):
        return False
    data = payload.get('data')
    if not isinstance(data, dict) or str(data.get('gameID')) != '1':
        return False
    info = data.get('result_list')
    if not isinstance(info, dict) or (data.get('resultID') is not None and str(data['resultID']) != str(match.match_id)):
        return False
    names, provenance = resolve_team_names(data, schedule, {side: info.get(f'{side}_name') for side in ('red', 'blue')})
    return (provenance['selected_source'] == 'schedule'
            and (names['red'] != match.red_team_name or names['blue'] != match.blue_team_name))


def _queue_series_results(series, raw_dir):
    schedule = series.schedule()
    for rid in json.loads(series.result_ids or '[]'):
        previous = db.session.query(SyncTask).filter_by(result_id=rid).first()
        if previous is not None and previous.series_id not in (None, series.series_id) and db.session.get(HistorySeries, previous.series_id):
            raise SourceError(f'result {rid}: 在两个已发现系列中重复出现，不能覆盖关联')
        task = get_task(rid, schedule)
        if task.status in ('skipped', 'failed', 'running'):
            continue
        match = db.session.query(Match).filter_by(match_id=rid).first()
        metadata = (match is not None and match.tournament_id == series.tournament_id
                    and match.series_id == series.series_id
                    and (series.scheduled_at is None or (match.date_source == 'schedule' and match.date == series.scheduled_at)))
        raw = raw_dir / 'scoregg' / f'{rid}.json'
        if _cached_team_names_changed(match, schedule, raw):
            task.status, task.next_retry_at = 'queued', None
            continue
        if task.status == 'source_incomplete' and (match is None or metadata):
            continue
        if not metadata or not _structure_complete(match) or not raw.is_file():
            task.status, task.next_retry_at = 'queued', None


def _discover_resultlist(client, series, raw_dir, now):
    if _pending(series.schedule(), now):
        _finish(series, 'pending', '官网待赛或单局战报尚未发布，未请求 resultlist')
        return
    _start(series)
    try:
        payload = client.get_result_list(series.series_id)
    except SourceHTTPError as exc:
        if exc.status_code == 404 and series.source_status == '1':
            _finish(series, 'pending', '进行中系列尚未发布 resultlist，HTTP404 已审计')
            return
        raise
    ids = result_ids_from_list(payload, series.series_id)
    raw = _archive(raw_dir / 'history' / 'resultlists' / f'{series.series_id}.json', payload)
    series.result_ids = json.dumps(ids)
    if not ids:
        _finish(series, 'pending', '已发布系列暂无单局 ID；保留空列表依据', raw)
        return
    _queue_series_results(series, raw_dir)
    if series.source_status == '1':
        _finish(series, 'pending', '进行中系列已发现当前单局；下一次刷新继续读取发布清单', raw)
    else:
        _finish(series, 'discovered', raw=raw)


def _pending_stage_refreshes(max_attempts, *, due_only=True):
    """待发布系列只能通过未耗尽、未处于失败退避的父阶段刷新。"""
    series = db.session.query(HistorySeries.stage_id).filter(HistorySeries.status == 'pending')
    if due_only:
        series = series.filter(HistorySeries.next_retry_at <= utc_now())
    return db.session.query(HistoryStage).filter(
        HistoryStage.id.in_(series), HistoryStage.failure_count < max_attempts,
        HistoryStage.status.in_(['queued', 'failed', 'pending', 'discovered']),
        or_(HistoryStage.status != 'failed', HistoryStage.next_retry_at.is_(None),
            HistoryStage.next_retry_at <= utc_now()),
    )


def _refresh_due_pending(max_attempts=5):
    # 只有读取阶段赛程才能知道 pub0 是否变化；不能凭持久错误文本猜测。
    for stage in _pending_stage_refreshes(max_attempts).all():
        stage.status, stage.next_retry_at = 'queued', None
    for stage in _ready(db.session.query(HistoryStage).filter_by(status='pending'), HistoryStage,
                        max_attempts, include_pending=True).all():
        stage.status, stage.next_retry_at = 'queued', None
    for tour in db.session.query(HistoryTournament).filter_by(status='discovered').filter(
            HistoryTournament.next_retry_at <= utc_now()).all():
        tour.status, tour.next_retry_at = 'queued', None
    db.session.commit()


def _seed_known_legacy(limit=1000):
    rows = db.session.query(Match.match_id).outerjoin(SyncTask, SyncTask.result_id == Match.match_id).filter(
        Match.source == 'legacy', Match.verified.is_(False), SyncTask.id.is_(None),
    ).order_by(Match.match_id).limit(limit).all()
    for (rid,) in rows:
        get_task(rid)
    db.session.commit()
    return len(rows)


def _fetch_task(client, task, raw_dir, run_id, now):
    schedule = task.schedule()
    series = db.session.get(HistorySeries, task.series_id) if task.series_id else None
    if series is not None:
        schedule = series.schedule()
    series_allows_incomplete = (series is not None and series.source_status == '2'
                               and (series.scheduled_at is None or series.scheduled_at < now - timedelta(days=14)))
    existing = db.session.query(Match).filter_by(match_id=task.result_id).first()
    previous = (existing.team_name_provenance if existing is not None
                and existing.source == 'scoregg' and existing.verified else None)
    # 旧 CSV 只提供已知单局 ID；是否 LOL、是否结束必须由详情本身确认。
    legacy_candidate = (series is None
                        and (task.scheduled_at is None or task.scheduled_at < now - timedelta(days=14))
                        and existing is not None and existing.source == 'legacy' and not existing.verified)
    path = raw_dir / 'scoregg' / f'{task.result_id}.json'
    payload, reused = None, False
    # 已有原始详情可以重新核验并回填真实赛程；没有合法原始证据就必须请求。
    if path.is_file():
        try:
            encoded = path.read_bytes()
            cached = json.loads(encoded)
            cached_allows_incomplete = series_allows_incomplete or (
                legacy_candidate and has_finished_lol_evidence(cached, task.result_id))
            normalize_result(cached, task.result_id, schedule, allow_incomplete=cached_allows_incomplete,
                             prior_team_name_provenance=previous)
            payload, reused = cached, True
            schedule['detail_archive'] = {'raw_file': str(path), 'sha256': hashlib.sha256(encoded).hexdigest()}
        except (OSError, ValueError, TypeError):
            payload = None
    start_task(task.result_id, schedule, run_id)
    if payload is None:
        payload = client.get_result(task.result_id)
        raw_file, sha256 = _archive(path, payload)
        schedule['detail_archive'] = {'raw_file': raw_file, 'sha256': sha256}
    allow_incomplete = series_allows_incomplete or (legacy_candidate and has_finished_lol_evidence(payload, task.result_id))
    outcome = ingest_result(payload, task.result_id, schedule, run_id, allow_incomplete=allow_incomplete)
    return {**outcome.to_dict(), 'reused_raw': reused, 'raw_file': str(path)}


def _raw_repair_schedule(match=None, result_id=None):
    """保留来自已发现赛程的元数据；updated_at 不能冒充真实比赛日。"""
    result_id = match.match_id if match is not None else result_id
    task = db.session.query(SyncTask).filter_by(result_id=result_id).first()
    series_id = task.series_id if task is not None and task.series_id else (match.series_id if match is not None else None)
    series = db.session.get(HistorySeries, series_id) if series_id else None
    if series is not None:
        return series.schedule()
    schedule = task.schedule() if task is not None else {}
    if match is not None:
        for field in ('series_id', 'tournament_id', 'tournament_name'):
            if schedule.get(field) is None and getattr(match, field) is not None:
                schedule[field] = getattr(match, field)
        if schedule.get('scheduled_at') is None and match.date_source == 'schedule':
            schedule['scheduled_at'] = match.date
    return schedule


def _raw_repair_changes(normalized, result_id):
    changes = []
    for model, name, keys in ((Match, 'matches', ('match_id',)),
                              (Team, 'teams', ('match_id', 'team_name')),
                              (Player, 'players', ('match_id', 'team_name', 'position'))):
        existing = {tuple(getattr(row, key) for key in keys): row for row in
                    db.session.query(model).filter_by(match_id=result_id)}
        expected_keys = set()
        for values in normalized[name]:
            key = tuple(values[field] for field in keys)
            expected_keys.add(key)
            row = existing.get(key)
            for field, value in values.items():
                if value is not None and isinstance(model.__table__.c[field].type, String):
                    value = str(value)
                before = getattr(row, field) if row is not None else None
                if before != value:
                    changes.append({'table': name, 'key': key, 'field': field,
                                    'before': before, 'after': value})
        for key in existing.keys() - expected_keys:
            changes.append({'table': name, 'key': key, 'field': '__extra_row__',
                            'before': '超出已验证原始详情的自然键', 'after': None})
    return changes


def repair_verified_raw(raw_dir, reports_dir, *, apply=False, names_by_source_id=None):
    """零 HTTP 审计/重放已提升的行。调用方必须先备份并持有同一 PipelineLock。"""
    result_ids = [rid for (rid,) in db.session.query(Match.match_id).filter_by(
        source='scoregg', verified=True).order_by(Match.match_id)]
    return repair_archived_results(raw_dir, reports_dir, result_ids=result_ids, apply=apply,
                                   names_by_source_id=names_by_source_id)


def _check_recovery_references(recovered_names):
    for recovered in recovered_names:
        for reference in recovered['references']:
            encoded = Path(reference['raw_file']).read_bytes()
            if hashlib.sha256(encoded).hexdigest() != reference['raw_sha256']:
                raise ValueError('恢复昵称的原始依据 SHA 已改变')


def _repair_schedule_evidence(schedule):
    """冻结实际赛程阶段；未关联原件的 legacy 不制造第二来源。"""
    if 'source_row' not in schedule:
        return None
    archive = schedule.get('source_archive')
    series = db.session.get(HistorySeries, schedule['series_id'])
    stage = db.session.get(HistoryStage, series.stage_id)
    row = schedule['source_row']
    if archive is not None:
        encoded = Path(archive['raw_file']).read_bytes()
        if hashlib.sha256(encoded).hexdigest() != archive['sha256']:
            raise ValueError('赛程阶段原件 SHA 与持久依据不一致')
        rows = json.loads(encoded)
        if not isinstance(rows, list) or sum(item == row for item in rows) != 1:
            raise ValueError('赛程阶段原件未唯一包含持久赛程原行')
    return {'series_id': series.series_id, 'stage_id': stage.id, 'source_row': row,
            'source_row_sha256': hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                                          separators=(',', ':')).encode('utf-8')).hexdigest(),
            'source_archive': archive,
            'series_archive_binding': {'raw_file': series.schedule_raw_file, 'sha256': series.schedule_raw_sha256}}


def _check_schedule_evidence(evidence):
    if evidence is None:
        return
    current = db.session.query(HistorySeries.stage_id, HistorySeries.source_json,
                               HistorySeries.schedule_raw_file, HistorySeries.schedule_raw_sha256).filter_by(
        series_id=evidence['series_id']).first()
    if current is None or current.stage_id != evidence['stage_id'] or json.loads(current.source_json) != evidence['source_row']:
        raise ValueError('审计后持久赛程原行或阶段关联改变，未重放此局')
    archive = evidence['source_archive']
    binding = {'raw_file': current.schedule_raw_file, 'sha256': current.schedule_raw_sha256}
    if binding != evidence['series_archive_binding']:
        raise ValueError('审计后系列赛程版本绑定改变，未重放此局')
    if archive is None:
        return
    if binding['raw_file'] is None and binding['sha256'] is None:
        stage = db.session.query(HistoryStage.raw_file, HistoryStage.raw_sha256).filter_by(id=current.stage_id).first()
        if stage is None or stage.raw_file != archive['raw_file'] or stage.raw_sha256 != archive['sha256']:
            raise ValueError('审计后赛程阶段归档依据改变，未重放此局')
    if hashlib.sha256(Path(archive['raw_file']).read_bytes()).hexdigest() != archive['sha256']:
        raise ValueError('审计后赛程 raw hash 改变，未重放此局')


def repair_archived_results(raw_dir, reports_dir, *, result_ids, apply=False, names_by_source_id=None):
    """显式指定归档单局，先写 before/after 与身份依据，再原子重放；零 HTTP。"""
    raw_dir, reports_dir = Path(raw_dir), Path(reports_dir)
    report_id = str(uuid4())
    report = {'repair_id': report_id, 'mode': 'apply' if apply else 'audit',
              'started_at': utc_now().isoformat() + 'Z', 'request_count': 0,
              'rule': '以公开 raw 重建指标 NULL 与部分名单；昵称仅取唯一同源 ID 依据；战队名仅取同 BO/teamID 赛程依据；原 CSV/raw 不修改',
              'checked': 0, 'changed_records': 0, 'changed_fields': 0,
              'cleared_unsupported_fields': 0, 'applied': 0, 'blocked': 0, 'failed': 0, 'records': []}
    path = reports_dir / f'verified-raw-repair-{report_id}.json'
    for result_id in sorted({int(value) for value in result_ids}):
        match = db.session.query(Match).filter_by(match_id=result_id).first()
        raw = raw_dir / 'scoregg' / f'{result_id}.json'
        item = {'result_id': result_id, 'raw_file': str(raw)}
        expected_state = (match.source, match.verified) if match is not None else None
        item['previous_source_state'] = expected_state
        report['checked'] += 1
        try:
            encoded = raw.read_bytes()
            payload = json.loads(encoded)
            schedule = _raw_repair_schedule(match, result_id)
            schedule['detail_archive'] = {'raw_file': str(raw), 'sha256': hashlib.sha256(encoded).hexdigest()}
            item['schedule'] = schedule
            item['schedule_evidence'] = _repair_schedule_evidence(schedule)
            previous = (match.team_name_provenance if match is not None
                        and match.source == 'scoregg' and match.verified else None)
            normalized = normalize_result(payload, result_id, schedule, allow_incomplete=True,
                                          names_by_source_id=names_by_source_id, prior_team_name_provenance=previous)
            _check_recovery_references(normalized.get('recovered_player_names', []))
            item['sha256'] = hashlib.sha256(encoded).hexdigest()
            item['changes'] = _raw_repair_changes(normalized, result_id)
            item['source_incomplete'] = normalized.get('source_incomplete', [])
            item['missing_roster_slots'] = normalized.get('missing_roster_slots', [])
            item['recovered_player_names'] = normalized.get('recovered_player_names', [])
            item['invalid_metric_groups'] = normalized.get('invalid_metric_groups', [])
            item['team_name_provenance'] = {
                'before': match.team_name_provenance if match is not None else None,
                'after': normalized['matches'][0].get('team_name_provenance'),
            }
        except (OSError, ValueError, TypeError) as exc:
            item.update(status='blocked', error=f'{type(exc).__name__}: {exc}')
            report['blocked'] += 1
            report['records'].append(item)
            continue
        report['changed_records'] += bool(item['changes'])
        report['changed_fields'] += len(item['changes'])
        report['cleared_unsupported_fields'] += sum(change['after'] is None and change['before'] is not None
                                                  for change in item['changes'])
        item['status'] = 'ready'
        report['records'].append(item)
    # 首先持久化所有 before/after，再逐局原子执行；中断仍保留完整校正计划。
    journal = path.with_suffix('.jsonl') if apply else None
    if journal is not None:
        report['journal_file'] = str(journal)
    _archive(path, report)
    if apply:
        for item in report['records']:
            if item['status'] != 'ready':
                continue
            raw = Path(item['raw_file'])
            encoded = raw.read_bytes()
            if hashlib.sha256(encoded).hexdigest() != item['sha256']:
                item.update(status='blocked', error='审计后 raw hash 改变，未重放此局')
                report['blocked'] += 1
                continue
            match = db.session.query(Match).filter_by(match_id=item['result_id']).first()
            current_state = (match.source, match.verified) if match is not None else None
            if current_state != item['previous_source_state']:
                item.update(status='blocked', error='审计后来源/核验状态改变，未重放此局')
                report['blocked'] += 1
                continue
            try:
                _check_recovery_references(item['recovered_player_names'])
                _check_schedule_evidence(item['schedule_evidence'])
            except (OSError, ValueError, TypeError) as exc:
                item.update(status='blocked', error=str(exc))
                report['blocked'] += 1
                continue
            outcome = ingest_result(json.loads(encoded), item['result_id'], item['schedule'],
                                    allow_incomplete=True, replace_existing=True, names_by_source_id=names_by_source_id)
            item.update(status=outcome.status, error=outcome.error)
            if outcome.status in ('imported', 'source_incomplete'):
                report['applied'] += 1
            else:
                report['failed'] += 1
            # 大批量修复只追加本局执行结果；完整 before/after 已在首次审计文件中持久化。
            with journal.open('a', encoding='utf-8') as output:
                output.write(json.dumps({'result_id': item['result_id'], 'status': outcome.status,
                                         'error': outcome.error}, ensure_ascii=False) + '\n')
    report['finished_at'] = utc_now().isoformat() + 'Z'
    report['report_file'] = str(path)
    _archive(path, report)
    return report


def recover_interrupted_history():
    for model in (HistoryTournament, HistoryStage, HistorySeries):
        for entity in db.session.query(model).filter_by(status='running').all():
            entity.status, entity.next_retry_at = 'queued', None
            entity.last_error = '上一进程中断；从此实体继续，不重扫成功前缀'
    db.session.commit()


def _next_all(max_attempts):
    """先完成最早赛事的已有单局，再扩展同赛事系列/阶段，最后进入下一赛事。"""
    tours = _ready(db.session.query(HistoryTournament.tournament_id.label('tournament_id')), HistoryTournament, max_attempts)
    stages = _ready(db.session.query(HistoryStage.tournament_id.label('tournament_id')), HistoryStage, max_attempts)
    series = _ready(db.session.query(HistorySeries.tournament_id.label('tournament_id')), HistorySeries, max_attempts)
    results = _ready(db.session.query(SyncTask.tournament_id.label('tournament_id')).filter(
        SyncTask.result_id.is_not(None), SyncTask.tournament_id.is_not(None)), SyncTask, max_attempts, include_pending=True)
    work = tours.union(stages, series, results).subquery()
    tour = db.session.query(HistoryTournament).filter(HistoryTournament.tournament_id.in_(
        db.session.query(work.c.tournament_id))).order_by(HistoryTournament.start_date.is_(None),
                                                        HistoryTournament.start_date, HistoryTournament.tournament_id).first()
    if tour is not None:
        task = _ready(db.session.query(SyncTask).filter_by(tournament_id=tour.tournament_id).filter(
            SyncTask.result_id.is_not(None)), SyncTask, max_attempts, include_pending=True).order_by(
                SyncTask.scheduled_at, SyncTask.result_id).first()
        if task is not None:
            return 'result', task
        item = _ready(db.session.query(HistorySeries).filter_by(tournament_id=tour.tournament_id),
                      HistorySeries, max_attempts).order_by(HistorySeries.scheduled_at, HistorySeries.series_id).first()
        if item is not None:
            return 'series', item
        item = _ready(db.session.query(HistoryStage).filter_by(tournament_id=tour.tournament_id),
                      HistoryStage, max_attempts).order_by(HistoryStage.id).first()
        return ('stage', item) if item is not None else ('tournament', tour)
    task = _ready(db.session.query(SyncTask).filter(SyncTask.result_id.is_not(None)), SyncTask,
                  max_attempts, include_pending=True).order_by(SyncTask.result_id).first()
    if task is None and _seed_known_legacy():
        task = _ready(db.session.query(SyncTask).filter(SyncTask.result_id.is_not(None)), SyncTask,
                      max_attempts, include_pending=True).order_by(SyncTask.result_id).first()
    return ('result', task) if task is not None else (None, None)


def _state_counts(model):
    return dict(db.session.query(model.status, func.count()).group_by(model.status).all())


def coverage_report(max_attempts=5):
    """只读覆盖率；目录/阶段按赛事开始年，系列/单局按赛程，未知单列。"""
    tournament_states, stage_states, series_states = (_state_counts(m) for m in
                                                     (HistoryTournament, HistoryStage, HistorySeries))
    counts = {'catalog': tournament_states, 'stages': stage_states, 'series': series_states}
    counts['catalog']['total'] = sum(tournament_states.values())
    counts['stages']['total'] = sum(stage_states.values())
    counts['series']['total'] = sum(series_states.values())
    years = defaultdict(lambda: {'tournaments': 0, 'discovered_tournaments': 0, 'series': 0,
                                'discovered_results': 0, 'verified_results': 0, 'complete_results': 0,
                                'source_incomplete': 0, 'pending_series': 0, 'failed_tasks': 0})
    for year, status, count in db.session.query(func.extract('year', HistoryTournament.start_date),
                                              HistoryTournament.status, func.count()).group_by(
                                                  func.extract('year', HistoryTournament.start_date), HistoryTournament.status):
        key = str(int(year)) if year else 'unknown'
        years[key]['tournaments'] += count
        years[key]['discovered_tournaments'] += count if status == 'discovered' else 0
        years[key]['failed_tasks'] += count if status == 'failed' else 0
    for year, count in db.session.query(func.extract('year', HistoryTournament.start_date), func.count()).join(
            HistoryStage, HistoryStage.tournament_id == HistoryTournament.tournament_id).filter(
                HistoryStage.status == 'failed').group_by(func.extract('year', HistoryTournament.start_date)):
        key = str(int(year)) if year else 'unknown'
        years[key]['failed_tasks'] += count
    for year, status, count in db.session.query(func.extract('year', HistorySeries.scheduled_at),
                                              HistorySeries.status, func.count()).group_by(
                                                  func.extract('year', HistorySeries.scheduled_at), HistorySeries.status):
        key = str(int(year)) if year else 'unknown'
        years[key]['series'] += count
        years[key]['pending_series'] += count if status == 'pending' else 0
        years[key]['failed_tasks'] += count if status == 'failed' else 0
    player_counts = db.session.query(Player.match_id.label('rid'), func.count().label('n')).group_by(Player.match_id).subquery()
    team_counts = db.session.query(Team.match_id.label('rid'), func.count().label('n')).group_by(Team.match_id).subquery()
    result_rows = db.session.query(SyncTask.result_id, SyncTask.status, HistorySeries.scheduled_at,
                                  Match.verified, Match.game_time, player_counts.c.n, team_counts.c.n).join(
        HistorySeries, HistorySeries.series_id == SyncTask.series_id).outerjoin(
            Match, Match.match_id == SyncTask.result_id).outerjoin(player_counts, player_counts.c.rid == SyncTask.result_id).outerjoin(
                team_counts, team_counts.c.rid == SyncTask.result_id).filter(SyncTask.result_id.is_not(None))
    results = Counter()
    for rid, status, schedule_date, verified, duration, players, teams in result_rows:
        key = str(schedule_date.year) if schedule_date else 'unknown'
        years[key]['discovered_results'] += 1
        results['discovered'] += 1
        results[status] += 1
        if verified:
            results['verified'] += 1
            years[key]['verified_results'] += 1
        if verified and duration is not None and duration > 1 and players == 10 and teams == 2 and status == 'imported':
            results['complete'] += 1
            years[key]['complete_results'] += 1
        if status == 'source_incomplete':
            years[key]['source_incomplete'] += 1
        if status == 'failed':
            years[key]['failed_tasks'] += 1
    counts['results'] = dict(results)
    counts['series']['unpublished'] = db.session.query(HistorySeries).filter_by(is_publist=0).count()
    counts['series']['without_date'] = db.session.query(HistorySeries).filter(HistorySeries.scheduled_at.is_(None)).count()
    legacy = {'unverified_matches': db.session.query(Match).filter_by(source='legacy', verified=False).count()}
    legacy['known_unmapped_tasks'] = db.session.query(SyncTask).outerjoin(
        HistorySeries, HistorySeries.series_id == SyncTask.series_id).filter(
            SyncTask.result_id.is_not(None), HistorySeries.series_id.is_(None)).count()
    unmapped_states = dict(db.session.query(SyncTask.status, func.count()).outerjoin(
        HistorySeries, HistorySeries.series_id == SyncTask.series_id).filter(
            SyncTask.result_id.is_not(None), HistorySeries.series_id.is_(None)).group_by(SyncTask.status).all())
    counts['known_unmapped_results'] = unmapped_states
    for year, count in db.session.query(func.extract('year', SyncTask.scheduled_at), func.count()).outerjoin(
            HistorySeries, HistorySeries.series_id == SyncTask.series_id).filter(
                SyncTask.result_id.is_not(None), HistorySeries.series_id.is_(None), SyncTask.status == 'failed').group_by(
                    func.extract('year', SyncTask.scheduled_at)):
        key = str(int(year)) if year else 'unknown'
        years[key]['failed_tasks'] += count
    unseeded_legacy = db.session.query(Match).outerjoin(SyncTask, SyncTask.result_id == Match.match_id).filter(
        Match.source == 'legacy', Match.verified.is_(False), SyncTask.id.is_(None)).count()
    ready = _ready(db.session.query(HistoryTournament), HistoryTournament, max_attempts, include_pending=True).count()
    ready += _ready(db.session.query(HistorySeries), HistorySeries, max_attempts).count()
    # pending 系列实际要刷新阶段；同一阶段只计一次，不能把受阻系列当可运行任务。
    stage_ids = _ready(db.session.query(HistoryStage.id), HistoryStage, max_attempts, include_pending=True).union(
        _pending_stage_refreshes(max_attempts).with_entities(HistoryStage.id)).subquery()
    ready += db.session.query(func.count()).select_from(stage_ids).scalar()
    ready += db.session.query(HistoryTournament).filter_by(status='discovered').filter(
        HistoryTournament.next_retry_at <= utc_now()).count()
    ready += _ready(db.session.query(SyncTask).filter(SyncTask.result_id.is_not(None)), SyncTask,
                    max_attempts, include_pending=True).count() + unseeded_legacy
    discovery_complete = bool(counts['catalog']['total']) and all(
        counts[name].get(state, 0) == 0 for name in ('catalog', 'stages', 'series')
        for state in ('queued', 'running', 'failed'))
    pending = counts['stages'].get('pending', 0) + counts['series'].get('pending', 0) + results.get('pending', 0)
    failures = sum(counts[n].get('failed', 0) for n in ('catalog', 'stages', 'series')) + results.get('failed', 0) + unmapped_states.get('failed', 0)
    complete_available = (discovery_complete and not ready and not pending and not failures
                          and not results.get('source_incomplete', 0)
                          and not any(unmapped_states.get(state, 0) for state in ('source_incomplete', 'pending', 'failed')))
    snapshot_completed = bool(counts['catalog']['total']) and not unseeded_legacy and all(
        counts[name].get(state, 0) == 0 for name in ('catalog', 'stages', 'series')
        for state in ('queued', 'running', 'failed')) and not any(
            results.get(state, 0) + unmapped_states.get(state, 0) for state in ('queued', 'running', 'failed'))
    deadlines = [db.session.query(func.min(model.next_retry_at)).filter(
        model.status.in_(['pending', 'failed', 'discovered']), model.failure_count < max_attempts,
        model.next_retry_at > utc_now(),
        model.result_id.is_not(None) if model is SyncTask else True).scalar()
        for model in (HistoryTournament, HistoryStage, SyncTask)]
    deadlines.append(db.session.query(func.min(HistorySeries.next_retry_at)).filter(
        HistorySeries.status.in_(['failed', 'discovered']), HistorySeries.failure_count < max_attempts,
        HistorySeries.next_retry_at > utc_now()).scalar())
    # 失败父阶段的退避时间由其自身提供；受阻系列不能提前唤醒空批次。
    deadlines.append(db.session.query(func.min(HistorySeries.next_retry_at)).filter(
        HistorySeries.status == 'pending', HistorySeries.failure_count < max_attempts,
        HistorySeries.next_retry_at > utc_now(), HistorySeries.stage_id.in_(
            _pending_stage_refreshes(max_attempts, due_only=False).with_entities(HistoryStage.id))).scalar())
    next_retry = min((value for value in deadlines if value is not None), default=None)
    exhausted = sum(db.session.query(model).filter(model.status == 'failed', model.failure_count >= max_attempts,
                    model.result_id.is_not(None) if model is SyncTask else True).count()
                    for model in (HistoryTournament, HistoryStage, HistorySeries, SyncTask))
    return {
        'scope': 'ScoreGG 公开 LOL 赛事目录及已知旧 CSV 单局；未知和未发布缺口保留',
        'updated_at': utc_now().isoformat() + 'Z', 'counts': counts, 'legacy': legacy,
        'years': [{'year': year, **values} for year, values in sorted(years.items())],
        'ready_tasks': ready, 'pending_publication': pending, 'failed_tasks': failures,
        'discovery_complete': discovery_complete, 'complete_available': complete_available,
        'snapshot_completed': snapshot_completed, 'has_runnable_work': bool(ready),
        'next_retry_at': next_retry.isoformat() + 'Z' if next_retry else None,
        'exhausted_tasks': exhausted,
        'date_basis': '目录和阶段按赛事开始年；系列及关联单局按 series.scheduled_at，'
                      '未关联单局按任务赛程；排除 updated_at，无日期归 unknown',
    }


def run_history(client, run, raw_dir, reports_dir, *, phase='all', now=None, max_attempts=5, refresh=False):
    """单批工作。每个成功实体立即持久化，预算退出仍可从下一实体继续。"""
    raw_dir, reports_dir = Path(raw_dir), Path(reports_dir)
    now = now or datetime.now()
    recover_interrupted_history()
    outcomes, details = [], {'phase': phase, 'scope': 'all_catalog_tournaments'}
    _seed_catalog(client, raw_dir, refresh)
    _refresh_due_pending(max_attempts)
    budget_error = None
    current = None
    try:
        if phase == 'all':
            while True:
                kind, entity = _next_all(max_attempts)
                if entity is None:
                    break
                client.budget.check()
                current = {'entity': kind, 'id': (entity.result_id if kind == 'result' else
                           entity.series_id if kind == 'series' else entity.cache_key if kind == 'stage' else entity.tournament_id)}
                try:
                    if kind == 'result':
                        outcomes.append(_fetch_task(client, entity, raw_dir, run.id, now))
                    elif kind == 'series':
                        _discover_resultlist(client, entity, raw_dir, now)
                    elif kind == 'stage':
                        _discover_stage(client, entity, raw_dir, now)
                    else:
                        _discover_tournament(client, entity, raw_dir, now)
                except (SourceError, OSError, ValueError) as exc:
                    if isinstance(exc, BudgetExceeded):
                        if kind == 'result':
                            mark_failure(entity.result_id, exc, entity.schedule(), run.id, status='queued')
                        raise
                    db.session.rollback()
                    if kind == 'result':
                        outcomes.append(mark_failure(entity.result_id, exc, entity.schedule(), run.id).to_dict())
                    else:
                        _finish(entity, 'failed', exc)
                        outcomes.append({**current, 'status': 'failed', 'error': str(exc)})
                if client.budget.count % 25 == 0:
                    _archive(reports_dir / 'history-progress.json', {'run_id': run.run_id, 'status': 'running',
                             'current': current, 'request_count': client.budget.count, 'outcomes_this_batch': len(outcomes)})
        if phase == 'discover':
            while True:
                tour = _ready(db.session.query(HistoryTournament), HistoryTournament, max_attempts).order_by(
                    HistoryTournament.start_date.is_(None), HistoryTournament.start_date, HistoryTournament.tournament_id).first()
                if tour is None:
                    break
                client.budget.check()
                current = {'entity': 'tournament', 'id': tour.tournament_id}
                try:
                    _discover_tournament(client, tour, raw_dir, now)
                except (SourceError, OSError, ValueError) as exc:
                    if isinstance(exc, BudgetExceeded):
                        raise
                    db.session.rollback()
                    _finish(tour, 'failed', exc)
                    outcomes.append({**current, 'status': 'failed', 'error': str(exc)})
            while True:
                stage = _ready(db.session.query(HistoryStage), HistoryStage, max_attempts).join(
                    HistoryTournament).order_by(HistoryTournament.start_date.is_(None), HistoryTournament.start_date,
                                                HistoryStage.tournament_id, HistoryStage.id).first()
                if stage is None:
                    break
                client.budget.check()
                current = {'entity': 'stage', 'id': stage.cache_key, 'tournament_id': stage.tournament_id}
                try:
                    _discover_stage(client, stage, raw_dir, now)
                except (SourceError, OSError, ValueError) as exc:
                    if isinstance(exc, BudgetExceeded):
                        raise
                    db.session.rollback()
                    _finish(stage, 'failed', exc)
                    outcomes.append({**current, 'status': 'failed', 'error': str(exc)})
            while True:
                series = _ready(db.session.query(HistorySeries), HistorySeries, max_attempts).order_by(
                    HistorySeries.scheduled_at.is_(None), HistorySeries.scheduled_at, HistorySeries.series_id).first()
                if series is None:
                    break
                client.budget.check()
                current = {'entity': 'series', 'id': series.series_id}
                try:
                    _discover_resultlist(client, series, raw_dir, now)
                except (SourceError, OSError, ValueError) as exc:
                    if isinstance(exc, BudgetExceeded):
                        raise
                    db.session.rollback()
                    _finish(series, 'failed', exc)
                    outcomes.append({**current, 'status': 'failed', 'error': str(exc)})
        if phase == 'fetch':
            _seed_known_legacy()
            while True:
                task = _ready(db.session.query(SyncTask).filter(SyncTask.result_id.is_not(None)), SyncTask,
                              max_attempts, include_pending=True).order_by(
                    SyncTask.scheduled_at.is_(None), SyncTask.scheduled_at, SyncTask.result_id).first()
                if task is None:
                    if _seed_known_legacy() == 0:
                        break
                    continue
                client.budget.check()
                current = {'entity': 'result', 'id': task.result_id}
                try:
                    outcomes.append(_fetch_task(client, task, raw_dir, run.id, now))
                except (SourceError, OSError, ValueError) as exc:
                    if isinstance(exc, BudgetExceeded):
                        mark_failure(task.result_id, exc, task.schedule(), run.id, status='queued')
                        raise
                    outcomes.append(mark_failure(task.result_id, exc, task.schedule(), run.id).to_dict())
                if len(outcomes) % 25 == 0:
                    _archive(reports_dir / 'history-progress.json', {'run_id': run.run_id, 'status': 'running',
                             'current': current, 'request_count': client.budget.count, 'outcomes_this_batch': len(outcomes)})
    except BudgetExceeded as exc:
        budget_error = str(exc)
        db.session.rollback()
        recover_interrupted_history()
    details.update(current=current, budget_error=budget_error, coverage=coverage_report(max_attempts))
    status = 'budget_exhausted' if budget_error else ('partial' if any(x.get('status') == 'failed' for x in outcomes) else 'completed')
    if status == 'completed' and phase == 'all' and details['coverage']['failed_tasks']:
        status = 'waiting_retry'
    _archive(reports_dir / 'history-progress.json', {'run_id': run.run_id, 'status': status,
             'request_count': client.budget.count, **details})
    return outcomes, details, status
