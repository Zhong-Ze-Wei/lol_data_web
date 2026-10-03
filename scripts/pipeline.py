"""统一数据入口：python -m scripts.pipeline daily / backfill / retry / import-legacy。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app import create_app, db
from app.models.sync import SyncRun, SyncTask, utc_now
from app.models.match import Match
from app.services.ingestion import get_task, start_task, finish_task, ingest_result, mark_failure
from app.services.legacy_import import import_legacy
from app.services.spider import BudgetExceeded, RequestBudget, ScoreGGClient, SourceError, SourceHTTPError, discover_series


ROOT_DIR = Path(__file__).resolve().parents[1]


class AlreadyRunning(RuntimeError):
    pass


class PipelineLock:
    """OS 释放进程锁；即使程序崩溃也没有需要手动删除的过期锁。"""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.handle.write(b'\0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise AlreadyRunning('已有采集/导入任务正在运行，本次未启动') from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.handle.seek(0)
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    temp = path.with_suffix(path.suffix + f'.{os.getpid()}.tmp')
    temp.write_bytes(encoded)
    os.replace(temp, path)
    return hashlib.sha256(encoded).hexdigest()


def _fetch_result(client, result_id, schedule, run, raw_dir, outcomes):
    start_task(result_id, schedule, run.id)
    try:
        payload = client.get_result(result_id)
        path = Path(raw_dir) / 'scoregg' / f'{result_id}.json'
        digest = atomic_json(path, payload)
        outcome = ingest_result(payload, result_id, schedule, run.id)
        item = {**outcome.to_dict(), 'raw_file': str(path), 'sha256': digest}
    except BudgetExceeded as exc:
        mark_failure(result_id, exc, schedule, run.id, status='queued')
        raise
    except SourceError as exc:
        item = mark_failure(result_id, exc, schedule, run.id).to_dict()
    except OSError as exc:
        item = mark_failure(result_id, f'原始响应归档失败: {exc}', schedule, run.id).to_dict()
    outcomes.append(item)
    return item


def _series_pending_reason(schedule, now):
    # 官网 status 是比赛进度，is_publist 是单局战报发布状态，不能相互替代。
    if schedule.get('status') == '0' or (schedule.get('scheduled_at') and schedule['scheduled_at'] > now):
        return f"赛程待赛 (status={schedule.get('status')})；次日复查"
    if str(schedule.get('is_publist')) == '0':
        return f"官网单局战报尚未发布 (status={schedule.get('status')}, is_publist=0)；比分不等于选手明细，次日复查"
    return None


def _fetch_series(client, schedule, run, raw_dir, outcomes, max_attempts, now):
    pending_reason = _series_pending_reason(schedule, now)
    if pending_reason:
        task = finish_task(None, 'pending', pending_reason, schedule, run.id)
        db.session.commit()
        outcomes.append({'series_id': schedule['series_id'], 'status': 'pending', 'error': task.last_error,
                         'source_status': schedule.get('status'), 'is_publist': schedule.get('is_publist'),
                         'series_score': schedule.get('series_score')})
        return
    existing = get_task(schedule=schedule, run_id=run.id)
    if existing.status == 'failed' and existing.failure_count >= max_attempts:
        outcomes.append({'series_id': schedule['series_id'], 'status': 'failed', 'error': '系列赛已达到持久失败重试上限'})
        db.session.commit()
        return
    start_task(schedule=schedule, run_id=run.id)
    try:
        result_ids = client.get_result_ids(schedule['series_id'])
    except BudgetExceeded as exc:
        mark_failure(None, exc, schedule, run.id, status='queued')
        raise
    except SourceError as exc:
        if isinstance(exc, SourceHTTPError) and exc.status_code == 404 and schedule.get('status') == '1':
            outcomes.append({**mark_failure(None, '进行中系列尚未发布结果列表；次日复查', schedule, run.id, status='pending').to_dict(),
                             'series_id': schedule['series_id']})
            return
        outcomes.append({**mark_failure(None, exc, schedule, run.id).to_dict(), 'series_id': schedule['series_id']})
        return
    if not result_ids:
        finish_task(None, 'pending', '系列赛尚无单局结果；次日复查', schedule, run.id)
        db.session.commit()
        outcomes.append({'series_id': schedule['series_id'], 'status': 'pending', 'error': '系列赛尚无单局结果'})
        return
    for result_id in result_ids:
        get_task(result_id, schedule, run.id)
    finish_task(None, 'imported', schedule=schedule, run_id=run.id)
    db.session.commit()
    for result_id in result_ids:
        task = get_task(result_id, schedule, run.id)
        if task.status == 'failed' and task.failure_count >= max_attempts:
            outcomes.append({'result_id': result_id, 'status': 'failed', 'error': '已达到持久失败重试上限；检查任务后显式提高 --max-attempts'})
            continue
        _fetch_result(client, result_id, schedule, run, raw_dir, outcomes)


def run_pipeline(command, *, client=None, start=None, end=None, data_dir=None,
                 raw_dir=None, reports_dir=None, max_requests=400, max_seconds=900,
                 window_days=14, now=None, force=False, max_attempts=5, tournament_ids=None, limit=20):
    """需要应用上下文；返回 JSON 报告及进程退出码，不隐藏上游/入库失败。"""
    raw_dir = Path(raw_dir or ROOT_DIR / 'data' / 'raw')
    reports_dir = Path(reports_dir or ROOT_DIR / 'data' / 'reports')
    client = client or ScoreGGClient(RequestBudget(max_requests, max_seconds))
    now = now or datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    # 此函数由进程锁保护；上次异常退出的 running 记录可安全改为 interrupted。
    for previous in db.session.query(SyncRun).filter_by(status='running').all():
        previous.status = 'interrupted'
        previous.finished_at = utc_now()
        previous.error = '上一进程退出前没有完成运行报告'
    for task in db.session.query(SyncTask).filter_by(status='running').all():
        task.status = 'failed'
        task.last_error = '上一采集进程中断，可重试'
        task.next_retry_at = utc_now()
    run = SyncRun(command=command, status='running')
    db.session.add(run)
    db.session.commit()
    outcomes = []
    details = {}
    status = 'completed'
    error = None
    try:
        if command == 'import-legacy':
            if data_dir is None:
                raise ValueError('import-legacy 需要 --data-dir')
            details['legacy'] = import_legacy(data_dir, reports_dir, run.run_id, force=force)
            run.imported = details['legacy']['imported_matches']
        elif command == 'backfill':
            if start is None or end is None or start < 1 or end < start:
                raise ValueError('backfill 需要合法 --start / --end（resultID 闭区间）')
            details.update(start_result_id=start, end_result_id=end)
            for result_id in range(start, end + 1):
                details['next_result_id'] = result_id
                _fetch_result(client, result_id, None, run, raw_dir, outcomes)
                details['next_result_id'] = result_id + 1
        elif command == 'daily':
            schedules, discovered = discover_series(client, now, window_days, tournament_ids,
                                                    discovery_requests=max(1, min(120, client.budget.max_requests // 3)))
            details.update(discovered)
            details['window_start'] = (now - timedelta(days=window_days)).isoformat()
            details['window_end'] = now.isoformat()
            for schedule in schedules:
                reason = _series_pending_reason(schedule, now)
                if reason:
                    finish_task(None, 'pending', reason, schedule, run.id)
                    outcomes.append({'series_id': schedule['series_id'], 'status': 'pending', 'error': reason,
                                     'source_status': schedule.get('status'), 'is_publist': schedule.get('is_publist'),
                                     'series_score': schedule.get('series_score')})
                else:
                    get_task(schedule=schedule, run_id=run.id)
            db.session.commit()
            states = {task.series_id: task.status for task in db.session.query(SyncTask).filter(
                SyncTask.result_id.is_(None), SyncTask.series_id.in_([s['series_id'] for s in schedules])).all()}
            schedules.sort(key=lambda s: (s.get('status') != '0', states.get(s['series_id']) != 'imported'), reverse=True)
            for schedule in schedules:
                if _series_pending_reason(schedule, now) is None:
                    _fetch_series(client, schedule, run, raw_dir, outcomes, max_attempts, now)
            if discovered['discovery_errors']:
                status = 'partial'
                error = '部分赛事发现失败，见 discovery_errors'
            elif discovered['discovery_limited']:
                status = 'partial'
                error = '赛程发现达到分配预算，未完成赛事见 deferred_tournaments；结果请求预算已保留'
            elif discovered['source_stale']:
                status = 'stale'
                error = '上游未发现近窗口赛程；没有把旧数据标成最近更新'
        elif command == 'retry':
            query = db.session.query(SyncTask).filter(
                or_(SyncTask.status.in_(['queued', 'failed']),
                    (SyncTask.status == 'pending') & SyncTask.result_id.is_not(None)),
                SyncTask.failure_count < max_attempts,
            )
            if not force:
                query = query.filter(or_(SyncTask.next_retry_at.is_(None), SyncTask.next_retry_at <= utc_now()))
            tasks = query.order_by(SyncTask.updated_at.asc()).limit(max_requests).all()
            # 先快照自然键，提交后的 ORM 状态变化不影响本次选定集合。
            snapshots = [(t.result_id, t.schedule()) for t in tasks]
            details['selected_tasks'] = len(snapshots)
            details['pending_series_policy'] = '待赛/战报待发布系列由 daily 重新读取官网状态；retry 仅处理 queued/failed 及单局 pending'
            for result_id, schedule in snapshots:
                if result_id is not None:
                    _fetch_result(client, result_id, schedule, run, raw_dir, outcomes)
                else:
                    _fetch_series(client, schedule, run, raw_dir, outcomes, max_attempts, now)
        elif command == 'verify-legacy':
            if limit < 1:
                raise ValueError('verify-legacy --limit 必须为正数')
            result_ids = [row.match_id for row in db.session.query(Match).filter_by(source='legacy', verified=False)
                          .order_by(Match.date.desc(), Match.match_id.desc()).limit(limit).all()]
            details['selected_legacy_matches'] = len(result_ids)
            for result_id in result_ids:
                _fetch_result(client, result_id, None, run, raw_dir, outcomes)
        else:
            raise ValueError(f'未知采集命令: {command}')
    except BudgetExceeded as exc:
        status = 'budget_exhausted'
        error = str(exc)
    except Exception as exc:
        # CLI 运行边界：保存持久失败状态/报告并返回非零，不吞掉实际失败。
        db.session.rollback()
        status = 'failed'
        error = f'{type(exc).__name__}: {exc}'
    run.request_count = client.budget.count
    if command != 'import-legacy':
        run.imported = sum(item['status'] == 'imported' for item in outcomes)
    run.skipped = sum(item['status'] in ('skipped', 'pending') for item in outcomes)
    run.failed = sum(item['status'] == 'failed' for item in outcomes)
    if run.failed and status == 'completed':
        status = 'partial'
        error = '存在失败任务，可通过 retry 重试，见单局报告'
    run.status = status
    run.error = error
    run.finished_at = utc_now()
    details['outcomes'] = outcomes
    run.details = json.dumps(details, ensure_ascii=False, default=str)
    db.session.commit()
    report = run.to_dict()
    atomic_json(reports_dir / f'{run.run_id}.json', report)
    return report, 0 if status == 'completed' else 2


def parser():
    root = argparse.ArgumentParser(description='ScoreGG LOL 数据采集与历史迁移')
    sub = root.add_subparsers(dest='command', required=True)
    for command in ('daily', 'backfill', 'retry', 'import-legacy', 'verify-legacy'):
        child = sub.add_parser(command)
        child.add_argument('--max-requests', type=int, default=400)
        child.add_argument('--max-seconds', type=float, default=900)
        child.add_argument('--max-attempts', type=int, default=5)
        if command == 'daily':
            child.add_argument('--window-days', type=int, default=14)
            child.add_argument('--tournament-id', action='append', type=int, dest='tournament_ids')
        elif command == 'backfill':
            child.add_argument('--start', type=int, required=True, help='开始 resultID（含）')
            child.add_argument('--end', type=int, required=True, help='结束 resultID（含）')
        elif command == 'retry':
            child.add_argument('--force', action='store_true', help='人工重试时忽略等待时间，仍遵守请求与失败次数预算')
        elif command == 'verify-legacy':
            child.add_argument('--limit', type=int, default=20)
        else:
            child.add_argument('--data-dir', type=Path, required=True)
            child.add_argument('--force', action='store_true', help='即使文件 hash 未变也重新解析导入，仍保留已核验 LOL/非 LOL 结果')
    return root


def main(argv=None):
    arguments = vars(parser().parse_args(argv))
    if arguments.get('tournament_ids') is not None:
        arguments['tournament_ids'] = set(arguments['tournament_ids'])
    app = create_app()
    with app.app_context():
        db.create_all()
        try:
            with PipelineLock(ROOT_DIR / 'data' / '.sync.lock'):
                report, code = run_pipeline(**arguments)
        except AlreadyRunning as exc:
            print(json.dumps({'status': 'already_running', 'error': str(exc)}, ensure_ascii=False))
            return 3
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return code


if __name__ == '__main__':
    raise SystemExit(main())
