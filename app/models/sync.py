"""采集运行与任务状态；进程退出后仍可继续重试。"""

import json
from datetime import datetime, timezone
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
