"""后台执行器的会话与近期心跳；不以数据库运行记录推断进程存活。"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from uuid import uuid4

HEARTBEAT_INTERVAL_SECONDS = 15
HEARTBEAT_TIMEOUT_SECONDS = 90
ACTIVE_STATUSES = {"starting", "running", "continue", "daily_pause", "locked", "retry_later", "retry_wait"}


def worker_status(path, now=None):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"alive": False, "heartbeat_state": "invalid"}
    if not isinstance(state, dict):
        return {"alive": False, "heartbeat_state": "invalid"}
    # API只公开状态字段；历史文件即使有PID或额外配置也不转发。
    fields = ("session_id", "status", "reason", "batch", "current_batch", "last_completed_batch",
              "last_run_id", "request_count", "started_at", "updated_at", "heartbeat_at",
              "finished_at", "resume_at", "next_retry_at")
    result = {key: state[key] for key in fields if key in state}
    age = None
    heartbeat_state = "missing"
    if state.get("heartbeat_at"):
        try:
            heartbeat = datetime.fromisoformat(state["heartbeat_at"].replace("Z", "+00:00"))
            if heartbeat.tzinfo is None:
                raise ValueError("心跳必须包含时区")
            age = ((now or datetime.now(timezone.utc)) - heartbeat).total_seconds()
            heartbeat_state = "future" if age < 0 else "fresh" if age <= HEARTBEAT_TIMEOUT_SECONDS else "expired"
        except (TypeError, ValueError, AttributeError):
            heartbeat_state = "invalid"
    result.update(alive=state.get("running") is True and state.get("status") in ACTIVE_STATUSES and heartbeat_state == "fresh",
                  heartbeat_state=heartbeat_state, heartbeat_age_seconds=age,
                  heartbeat_timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS)
    return result


class WorkerRuntime:
    """同一会话串行写业务状态和心跳，收尾先停线程再写终态。"""

    def __init__(self, path, writer, interval=HEARTBEAT_INTERVAL_SECONDS, clock=None):
        self.path = Path(path)
        self.writer = writer
        self.interval = interval
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = Lock()
        self.stop_event = Event()
        self.thread = None
        self.state = {}

    def __enter__(self):
        self.state = {"session_id": str(uuid4()), "status": "starting", "running": True,
                      "batch": 0, "current_batch": None, "last_completed_batch": None,
                      "started_at": self.clock().isoformat()}
        self.update()
        self.thread = Thread(target=self._heartbeat, daemon=True, name="history-heartbeat")
        self.thread.start()
        return self

    def _write(self):
        self.state["heartbeat_at"] = self.clock().isoformat()
        for attempt in range(3):
            try:
                self.writer(self.path, self.state)
                return
            except PermissionError as exc:
                # Windows读取者短暂持有目标文件时，原子替换可能遇到共享冲突。
                if getattr(exc, "winerror", None) not in (5, 32) or attempt == 2:
                    raise
                time.sleep(0.05)

    def update(self, **values):
        with self.lock:
            self.state.update(values, updated_at=self.clock().isoformat())
            self._write()

    def _heartbeat(self):
        while not self.stop_event.wait(self.interval):
            with self.lock:
                try:
                    self._write()
                except OSError:
                    logging.warning("后台心跳文件暂时写入失败，下一周期重试。")

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop_event.set()
        self.thread.join()
        if exc_type is not None:
            self.state.update(status="stopped" if issubclass(exc_type, (KeyboardInterrupt, SystemExit)) else "failed",
                              reason="interrupted" if issubclass(exc_type, (KeyboardInterrupt, SystemExit)) else "worker_error")
        elif self.state["status"] not in ("completed", "failed", "stopped"):
            self.state.update(status="stopped", reason="worker_exit")
        self.update(running=False, current_batch=None, finished_at=self.clock().isoformat())
