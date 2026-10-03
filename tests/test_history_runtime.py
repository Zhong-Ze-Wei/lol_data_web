import json
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest

from app.services.history_runtime import WorkerRuntime, worker_status
from scripts import history_worker
from scripts.pipeline import atomic_json

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize('seconds,state,alive', [(0, 'fresh', True), (90, 'fresh', True),
                                              (91, 'expired', False), (-1, 'future', False)])
def test_worker_heartbeat_lease_rejects_expiry_and_future_clock(tmp_path, seconds, state, alive):
    path = tmp_path / 'worker.json'
    atomic_json(path, {'status': 'running', 'running': True, 'heartbeat_at': (NOW - timedelta(seconds=seconds)).isoformat()})
    result = worker_status(path, NOW)
    assert result['alive'] is alive and result['heartbeat_state'] == state


@pytest.mark.parametrize('heartbeat', [None, 'bad', '2026-10-03T12:00:00', 123])
def test_missing_or_invalid_heartbeat_does_not_reuse_continue_as_alive(tmp_path, heartbeat):
    path = tmp_path / 'worker.json'
    atomic_json(path, {'status': 'continue', 'running': True, 'batch': 2, 'heartbeat_at': heartbeat})
    assert worker_status(path, NOW)['alive'] is False


@pytest.mark.parametrize('status', ['stopped', 'completed', 'failed'])
def test_final_status_is_not_alive_even_before_cleanup_finishes(tmp_path, status):
    path = tmp_path / 'worker.json'
    atomic_json(path, {'status': status, 'running': True, 'heartbeat_at': NOW.isoformat()})
    assert worker_status(path, NOW)['alive'] is False


def test_new_session_resets_old_batch_and_finally_prevents_late_heartbeat(tmp_path):
    path = tmp_path / 'worker.json'
    atomic_json(path, {'session_id': 'old', 'status': 'continue', 'batch': 2})
    pulse = Event()
    def write(path, state):
        atomic_json(path, state)
        pulse.set()
    with WorkerRuntime(path, write, interval=0.01) as runtime:
        state = json.loads(path.read_text())
        assert state['session_id'] != 'old' and state['batch'] == 0
        assert state['current_batch'] is None and state['last_completed_batch'] is None
        runtime.update(status='running', current_batch=1)
        assert worker_status(path)['current_batch'] == 1
        runtime.update(status='daily_pause', current_batch=None)
        pulse.clear()
        assert pulse.wait(1)  # 等待期间也收到新的心跳，不启动真实采集。
        assert worker_status(path)['alive'] is True
    stopped = path.read_bytes()
    assert worker_status(path)['alive'] is False
    assert json.loads(stopped)['status'] == 'stopped'
    assert runtime.thread.is_alive() is False
    assert path.read_bytes() == stopped


def test_interrupt_writes_stopped_and_clears_current_batch(tmp_path):
    path = tmp_path / 'worker.json'
    with pytest.raises(KeyboardInterrupt), WorkerRuntime(path, atomic_json) as runtime:
        runtime.update(status='running', current_batch=1)
        raise KeyboardInterrupt
    state = json.loads(path.read_text())
    assert state['status'] == 'stopped' and state['reason'] == 'interrupted'
    assert state['running'] is False and state['current_batch'] is None


@pytest.mark.parametrize('winerror', [5, 32])
def test_windows_reader_sharing_conflict_retries_atomically(tmp_path, winerror):
    path = tmp_path / 'worker.json'
    attempts = []
    def write(path, state):
        attempts.append(state['status'])
        if len(attempts) == 1:
            error = PermissionError('模拟Windows读取者仍持有文件')
            error.winerror = winerror
            raise error
        atomic_json(path, state)
    with WorkerRuntime(path, write):
        assert worker_status(path)['alive'] is True
    assert attempts == ['starting', 'starting', 'stopped']
    assert worker_status(path)['alive'] is False


@pytest.mark.parametrize('error_type,winerror,attempt_count', [
    (PermissionError, 5, 3), (PermissionError, 32, 3),
    (PermissionError, 13, 1), (PermissionError, None, 1), (OSError, None, 1)])
def test_runtime_write_retry_is_bounded_and_other_io_errors_fail_immediately(tmp_path, error_type, winerror, attempt_count):
    attempts = []
    def write(path, state):
        attempts.append(1)
        error = error_type('模拟状态文件写入失败')
        if winerror is not None:
            error.winerror = winerror
        raise error
    with pytest.raises(error_type), WorkerRuntime(tmp_path / 'worker.json', write):
        pytest.fail('写入失败不应进入采集会话')
    assert len(attempts) == attempt_count


def test_transient_heartbeat_io_failure_does_not_kill_waiting_session(tmp_path, caplog):
    path = tmp_path / 'worker.json'
    received = Event()
    heartbeats = 0
    def write(path, state):
        nonlocal heartbeats
        if state['status'] == 'daily_pause':
            heartbeats += 1
            if heartbeats == 2:
                raise OSError('模拟一次心跳IO失败')
            if heartbeats > 2:
                received.set()
        atomic_json(path, state)
    with WorkerRuntime(path, write, interval=0.01) as runtime:
        runtime.update(status='daily_pause')
        assert received.wait(1)
        assert runtime.thread.is_alive() and worker_status(path)['alive']
    assert '下一周期重试' in caplog.text
    assert worker_status(path)['alive'] is False


def batch_result(code=4, coverage=None):
    if code == 3:
        # pipeline争锁只返回already_running，不存在实际SyncRun或批次报告。
        return SimpleNamespace(returncode=3, stderr='', stdout=json.dumps({'status': 'already_running', 'error': '已有采集任务'}))
    return SimpleNamespace(returncode=code, stderr='', stdout=json.dumps({
        'run_id': 'new-first-run', 'request_count': 3, 'details': {'coverage': coverage or {}}}))


def test_finite_worker_first_batch_is_current_then_stops_without_claiming_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(history_worker, 'daily_pause_seconds', lambda _: 0)
    path = tmp_path / 'data' / 'history-worker.json'
    atomic_json(path, {'status': 'continue', 'batch': 2})
    def run(*args, **kwargs):
        current = worker_status(path)
        assert current['alive'] and current['current_batch'] == 1 and current['batch'] == 0
        return batch_result()
    monkeypatch.setattr(history_worker.subprocess, 'run', run)
    assert history_worker.run_worker(10, 30, max_batches=1) == 0
    state = json.loads(path.read_text())
    assert state['status'] == 'stopped' and state['reason'] == 'batch_limit'
    assert state['last_completed_batch'] == 1 and state['last_run_id'] == 'new-first-run'
    assert worker_status(path)['alive'] is False


@pytest.mark.parametrize('code,coverage,waiting', [(3, {}, 'locked'),
    (2, {'next_retry_at': '2026-10-04T12:00:00Z'}, 'retry_later'),
    (2, {'has_runnable_work': True}, 'retry_wait')])
def test_worker_wait_states_keep_a_live_lease_without_claiming_collection(tmp_path, monkeypatch, code, coverage, waiting):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(history_worker, 'daily_pause_seconds', lambda _: 0)
    monkeypatch.setattr(history_worker.subprocess, 'run', lambda *args, **kwargs: batch_result(code, coverage))
    observed = []
    def wait(*args):
        state = worker_status(tmp_path / 'data' / 'history-worker.json')
        observed.append(state['status'])
        assert state['alive'] and state['current_batch'] is None and state['resume_at']
    monkeypatch.setattr(history_worker.time, 'sleep', wait)
    monkeypatch.setattr(history_worker, 'wait_until', wait)
    assert history_worker.run_worker(10, 30, max_batches=1) == 0
    assert observed == [waiting]


def test_real_lock_payload_does_not_count_as_completed_batch_or_erase_last_run(tmp_path, monkeypatch):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(history_worker, 'daily_pause_seconds', lambda _: 0)
    path = tmp_path / 'data' / 'history-worker.json'
    outcomes = iter([batch_result(3), batch_result(4), batch_result(3)])
    current_batches = []
    locked_states = []
    def run(*args, **kwargs):
        current_batches.append(worker_status(path)['current_batch'])
        return next(outcomes)
    def wait(*args):
        locked_states.append(worker_status(path))
    monkeypatch.setattr(history_worker.subprocess, 'run', run)
    monkeypatch.setattr(history_worker.time, 'sleep', wait)
    assert history_worker.run_worker(10, 30, max_batches=3) == 0
    assert current_batches == [1, 1, 2]
    first, second = locked_states
    assert first['status'] == second['status'] == 'locked'
    assert first['last_completed_batch'] is None and first['batch'] == 0
    assert first.get('last_run_id') is None and first.get('request_count') is None
    assert second['last_completed_batch'] == second['batch'] == 1
    assert second['last_run_id'] == 'new-first-run' and second['request_count'] == 3
    final = worker_status(path)
    assert final['last_completed_batch'] == 1 and final['last_run_id'] == 'new-first-run'
    assert final['request_count'] == 3 and final['alive'] is False


def test_daily_yield_and_snapshot_exit_write_distinct_runtime_states(tmp_path, monkeypatch):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(history_worker, 'daily_pause_seconds', lambda _: 10)
    def wait(*args):
        state = worker_status(tmp_path / 'data' / 'history-worker.json')
        assert state['status'] == 'daily_pause' and state['alive'] and state['resume_at']
    monkeypatch.setattr(history_worker, 'wait_until', wait)
    monkeypatch.setattr(history_worker.subprocess, 'run', lambda *args, **kwargs: batch_result(0, {'snapshot_completed': True, 'complete_available': False}))
    assert history_worker.run_worker(10, 30) == 0
    state = worker_status(tmp_path / 'data' / 'history-worker.json')
    assert state['status'] == 'completed' and state['alive'] is False


@pytest.mark.parametrize('failure,reason', [('timeout', 'batch_timeout'), ('report', 'invalid_report'), ('exit', 'batch_exit')])
def test_worker_failure_always_stops_heartbeat(tmp_path, monkeypatch, failure, reason):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(history_worker, 'daily_pause_seconds', lambda _: 0)
    def run(*args, **kwargs):
        if failure == 'timeout':
            raise history_worker.subprocess.TimeoutExpired('mock-command', 1)
        return SimpleNamespace(returncode=1 if failure == 'exit' else 0, stdout='bad-json', stderr='')
    monkeypatch.setattr(history_worker.subprocess, 'run', run)
    assert history_worker.run_worker(10, 30) == 2
    state = worker_status(tmp_path / 'data' / 'history-worker.json')
    assert state['status'] == 'failed' and state['reason'] == reason
    assert state['alive'] is False and state['current_batch'] is None and state['finished_at']
