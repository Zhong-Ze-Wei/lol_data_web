"""采集运行与任务状态；进程退出后仍可继续重试。"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncRun(db.Model):
    __tablename__ = 'sync_runs'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    command = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='running')
    started_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    finished_at = db.Column(db.DateTime)
    request_count = db.Column(db.Integer, nullable=False, default=0)
    imported = db.Column(db.Integer, nullable=False, default=0)
    skipped = db.Column(db.Integer, nullable=False, default=0)
    failed = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)
    details = db.Column(db.Text)

    def to_dict(self):
        return {
            'id': self.id, 'run_id': self.run_id, 'command': self.command,
            'status': self.status,
            'started_at': self.started_at.isoformat() + 'Z' if self.started_at else None,
            'finished_at': self.finished_at.isoformat() + 'Z' if self.finished_at else None,
            'request_count': self.request_count, 'imported': self.imported,
            'skipped': self.skipped, 'failed': self.failed, 'error': self.error,
            'details': json.loads(self.details) if self.details else None,
        }


class SyncTask(db.Model):
    __tablename__ = 'sync_tasks'

    id = db.Column(db.Integer, primary_key=True)
    task_key = db.Column(db.String(80), unique=True, nullable=False)
    result_id = db.Column(db.Integer, unique=True, index=True)
    series_id = db.Column(db.Integer, index=True)
    tournament_id = db.Column(db.Integer)
    tournament_name = db.Column(db.String(200))
    scheduled_at = db.Column(db.DateTime)
    run_id = db.Column(db.Integer, db.ForeignKey('sync_runs.id'))
    status = db.Column(db.String(30), nullable=False, default='queued', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text)
    next_retry_at = db.Column(db.DateTime, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    imported_at = db.Column(db.DateTime)

    def schedule(self):
        return {
            'series_id': self.series_id, 'tournament_id': self.tournament_id,
            'tournament_name': self.tournament_name, 'scheduled_at': self.scheduled_at,
        }


class HistoryTournament(db.Model):
    """官网 LOL 赛事目录；起止日期未知的赛事同样保留。"""

    __tablename__ = 'history_tournaments'

    tournament_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(30), nullable=False, default='queued', index=True)
    stage_count = db.Column(db.Integer, nullable=False, default=0)
    expected_game_count = db.Column(db.Integer)
    raw_file = db.Column(db.Text)
    raw_sha256 = db.Column(db.String(64))
    source_json = db.Column(db.Text)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text)
    next_retry_at = db.Column(db.DateTime)
    discovered_at = db.Column(db.DateTime)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class HistoryStage(db.Model):
    """阶段缓存的持久游标；数字子阶段和 p_ 父阶段不能混用。"""

    __tablename__ = 'history_stages'
    __table_args__ = (db.UniqueConstraint('tournament_id', 'cache_key', name='uq_history_stage_cache'),)

    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('history_tournaments.tournament_id'), nullable=False, index=True)
    cache_key = db.Column(db.String(60), nullable=False)
    parent_round_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(200))
    source_json = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default='queued', index=True)
    series_count = db.Column(db.Integer, nullable=False, default=0)
    raw_file = db.Column(db.Text)
    raw_sha256 = db.Column(db.String(64))
    attempts = db.Column(db.Integer, nullable=False, default=0)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text)
    next_retry_at = db.Column(db.DateTime)
    discovered_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class HistorySeries(db.Model):
    """赛程与战报发布状态；跨进程仍可判断待发布，不能靠错误文本猜。"""

    __tablename__ = 'history_series'

    series_id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('history_tournaments.tournament_id'), nullable=False, index=True)
    stage_id = db.Column(db.Integer, db.ForeignKey('history_stages.id'), nullable=False)
    scheduled_at = db.Column(db.DateTime, index=True)
    source_status = db.Column(db.String(10))
    is_publist = db.Column(db.Integer)
    team_a_score = db.Column(db.Integer)
    team_b_score = db.Column(db.Integer)
    source_json = db.Column(db.Text)
    schedule_raw_file = db.Column(db.Text)
    schedule_raw_sha256 = db.Column(db.String(64))
    status = db.Column(db.String(30), nullable=False, default='queued', index=True)
    result_ids = db.Column(db.Text, nullable=False, default='[]')
    raw_file = db.Column(db.Text)
    raw_sha256 = db.Column(db.String(64))
    attempts = db.Column(db.Integer, nullable=False, default=0)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text)
    next_retry_at = db.Column(db.DateTime)
    discovered_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    def schedule(self):
        schedule = {
            'series_id': self.series_id, 'tournament_id': self.tournament_id,
            'tournament_name': db.session.get(HistoryTournament, self.tournament_id).name,
            'scheduled_at': self.scheduled_at, 'status': self.source_status,
            'is_publist': self.is_publist,
            'series_score': {'team_a': self.team_a_score, 'team_b': self.team_b_score},
        }
        if self.source_json is not None:
            schedule['source_row'] = json.loads(self.source_json)
            archive = self._schedule_archive(schedule['source_row'])
            if archive is not None:
                schedule['source_archive'] = archive
        return schedule

    def _schedule_archive(self, row):
        if self.schedule_raw_file and self.schedule_raw_sha256:
            return {'raw_file': self.schedule_raw_file, 'sha256': self.schedule_raw_sha256}
        if self.schedule_raw_file is not None or self.schedule_raw_sha256 is not None:
            return None
        # 迁移前行没有版本绑定；只接受实际仍包含该行的阶段原件。
        stage = db.session.get(HistoryStage, self.stage_id)
        if stage is None or not stage.raw_file or not stage.raw_sha256:
            return None
        try:
            encoded = Path(stage.raw_file).read_bytes()
            rows = json.loads(encoded)
        except (OSError, ValueError):
            return None
        if (hashlib.sha256(encoded).hexdigest() != stage.raw_sha256
                or not isinstance(rows, list) or sum(item == row for item in rows) != 1):
            return None
        return {'raw_file': stage.raw_file, 'sha256': stage.raw_sha256}
