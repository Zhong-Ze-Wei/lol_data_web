import json
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from sqlalchemy import case, func

from app import db
from app.models.match import Match
from app.models.sync import SyncRun, SyncTask
from app.services.history import coverage_report

sync_bp = Blueprint("sync", __name__, url_prefix="/api/sync")


@sync_bp.get("/history")
def history_status():
    last_run = db.session.query(SyncRun).filter_by(command="history").order_by(SyncRun.started_at.desc()).first()
    data_dir = Path(current_app.config["DATA_DIR"])
    state_file, schedule_file = data_dir / "history-worker.json", data_dir / "history-schedule.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else None
    schedule = json.loads(schedule_file.read_text(encoding="utf-8-sig")) if schedule_file.is_file() else {"enabled": False}
    return jsonify(**coverage_report(), last_run=last_run.to_dict() if last_run else None,
                   worker=state, schedule=schedule)


@sync_bp.get("/status")
def sync_status():
    last_run = db.session.query(SyncRun).order_by(SyncRun.started_at.desc()).first()
    tasks = dict(db.session.query(SyncTask.status, func.count()).group_by(SyncTask.status).all())
    first, last = db.session.query(func.min(Match.date), func.max(Match.date)).filter(
        Match.date_source == "schedule",
    ).one()
    record_first, record_last = db.session.query(func.min(Match.date), func.max(Match.date)).one()
    confirmed, unconfirmed = db.session.query(
        func.sum(case(((Match.date_source == "schedule") & Match.date.isnot(None), 1), else_=0)),
        func.sum(case(((Match.date_source == "schedule") & Match.date.isnot(None), 0), else_=1)),
    ).one()
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
        record_range={"min_date": record_first.isoformat() if record_first else None,
                      "max_date": record_last.isoformat() if record_last else None},
        date_quality={"confirmed": confirmed or 0, "unconfirmed": unconfirmed or 0,
                      "policy": "时间分析仅使用已确认赛程，来源更新时间不代表比赛日期。"},
        verified_matches=db.session.query(func.count(Match.id)).filter(Match.verified.is_(True)).scalar(),
        legacy_matches=db.session.query(func.count(Match.id)).filter(Match.source == "legacy").scalar(),
    )
