import json
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from sqlalchemy import func

from app import db
from app.models.match import Match
from app.models.sync import SyncRun, SyncTask

sync_bp = Blueprint("sync", __name__, url_prefix="/api/sync")


@sync_bp.get("/status")
def sync_status():
    last_run = db.session.query(SyncRun).order_by(SyncRun.started_at.desc()).first()
    tasks = dict(db.session.query(SyncTask.status, func.count()).group_by(SyncTask.status).all())
    first, last = db.session.query(func.min(Match.date), func.max(Match.date)).one()
    schedule_file = Path(current_app.config["DATA_DIR"]) / "schedule.json"
    schedule = {
        "enabled": False,
        "time": current_app.config["SCHEDULE_TIME"],
        "timezone": current_app.config["SCHEDULE_TIMEZONE"],
        "mode": "windows",
    }
    if schedule_file.is_file():
        schedule.update(json.loads(schedule_file.read_text(encoding="utf-8-sig")))
    return jsonify(
        last_run=last_run.to_dict() if last_run else None,
        tasks=tasks,
        schedule=schedule,
        data_range={"min_date": first.isoformat() if first else None, "max_date": last.isoformat() if last else None},
        verified_matches=db.session.query(func.count(Match.id)).filter(Match.verified.is_(True)).scalar(),
        legacy_matches=db.session.query(func.count(Match.id)).filter(Match.source == "legacy").scalar(),
    )
