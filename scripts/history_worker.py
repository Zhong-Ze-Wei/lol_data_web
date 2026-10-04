"""连续执行有限预算的历史补采；每批由现有采集 CLI 独立持久化。"""

import argparse
import json
import logging
import math
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from scripts.pipeline import AlreadyRunning, PipelineLock, atomic_json
from app.services.history_runtime import WorkerRuntime

ROOT = Path(__file__).resolve().parents[1]
HK = timezone(timedelta(hours=8))


def daily_pause_seconds(now):
    """给 08:00 每日任务预留窗口，15 分钟历史批次在窗口前结束。"""
    local = now.astimezone(HK)
    start = local.replace(hour=7, minute=40, second=0, microsecond=0)
    end = local.replace(hour=8, minute=20, second=0, microsecond=0)
    return max(0, (end - local).total_seconds()) if start <= local < end else 0


def next_action(code, coverage):
    if code == 4:
        return "continue"
    if code == 3:
        return "locked"
    if code not in (0, 2):
        return "failed"
    if coverage.get("has_runnable_work"):
        return "continue"
    if coverage.get("snapshot_completed"):
        return "completed"
    if coverage.get("next_retry_at"):
        return "retry_later"
    return "failed"


def wait_until(instant):
    while (remaining := (instant - datetime.now(timezone.utc)).total_seconds()) > 0:
        time.sleep(min(60, remaining))


def run_worker(max_requests, max_seconds, max_batches=None, min_interval=0.2):
    if not math.isfinite(min_interval) or min_interval < 0:
        raise ValueError("请求间隔必须为有限非负秒数")
    state_file = ROOT / "data" / "history-worker.json"
    with WorkerRuntime(state_file, atomic_json) as runtime:
        return _run_batches(runtime, max_requests, max_seconds, max_batches, min_interval)


def _run_batches(runtime, max_requests, max_seconds, max_batches, min_interval=0.2):
    batches = 0
    attempts = 0
    while max_batches is None or attempts < max_batches:
        pause = daily_pause_seconds(datetime.now(timezone.utc))
        if pause:
            logging.info("每日采集优先，历史补采暂让出 %.0f 秒", pause)
            resume = datetime.now(timezone.utc) + timedelta(seconds=pause)
            runtime.update(status="daily_pause", current_batch=None, resume_at=resume.isoformat())
            wait_until(resume)
        command = [sys.executable, "-X", "utf8", "-m", "scripts.pipeline", "history",
                   "--phase", "all", "--max-requests", str(max_requests),
                   "--max-seconds", str(max_seconds), "--min-interval", str(min_interval)]
        runtime.update(status="running", current_batch=batches + 1, resume_at=None)
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                    encoding="utf-8", timeout=max_seconds + 180)
        except subprocess.TimeoutExpired:
            logging.error("历史采集批次超过执行期限；子进程已结束，持久任务可恢复。")
            runtime.update(status="failed", reason="batch_timeout")
            return 2
        attempts += 1
        if result.returncode not in (0, 2, 3, 4):
            logging.error("历史采集进程退出 %s：%s", result.returncode, result.stderr[-3000:])
            runtime.update(status="failed", reason="batch_exit", exit_code=result.returncode)
            return 2
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            logging.error("历史采集未返回有效报告：%s", result.stderr[-3000:])
            runtime.update(status="failed", reason="invalid_report")
            return 2
        coverage = report.get("details", {}).get("coverage", {})
        action = next_action(result.returncode, coverage)
        if result.returncode == 3:
            runtime.update(status=action, current_batch=None)
        else:
            batches += 1
            runtime.update(status=action, batch=batches, current_batch=None, last_completed_batch=batches,
                           last_run_id=report.get("run_id"), request_count=report.get("request_count", 0),
                           next_retry_at=coverage.get("next_retry_at"))
        logging.info("历史尝试 %s，动作 %s，已执行批次 %s，请求 %s，导入 %s，失败 %s", attempts, action, batches,
                      report.get("request_count", 0), report.get("imported", 0), report.get("failed", 0))
        if action == "completed":
            return 0
        if action == "failed":
            logging.error("历史补采仍有无法自动处理的缺口；请查看最后一批报告。")
            return 2
        if action == "locked":
            runtime.update(resume_at=(datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat())
            time.sleep(60)
        elif action == "retry_later":
            instant = datetime.fromisoformat(coverage["next_retry_at"].replace("Z", "+00:00"))
            resume = max(instant, datetime.now(timezone.utc) + timedelta(seconds=60))
            runtime.update(resume_at=resume.isoformat())
            wait_until(resume)
        elif result.returncode == 2:
            runtime.update(status="retry_wait", resume_at=(datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat())
            time.sleep(60)
    runtime.update(status="stopped", reason="batch_limit")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-requests", type=int, default=400)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--min-interval", type=float, default=0.2,
                        help="每批同一进程HTTP尝试的最小间隔（秒），默认0.2")
    args = parser.parse_args()
    if args.max_requests < 1 or not 1 <= args.max_seconds <= 900:
        parser.error("请求数必须为正数，单批时间必须为1–900秒")
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("批次数必须为正数")
    if not math.isfinite(args.min_interval) or args.min_interval < 0:
        parser.error("请求间隔必须为有限非负秒数")
    (ROOT / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / "logs" / "history-worker.log", maxBytes=5_000_000,
                                  backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[handler])
    try:
        with PipelineLock(ROOT / "data" / ".history-worker.lock"):
            return run_worker(args.max_requests, args.max_seconds, args.max_batches, args.min_interval)
    except AlreadyRunning:
        logging.info("已有历史补采执行器，本次未重复启动。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
