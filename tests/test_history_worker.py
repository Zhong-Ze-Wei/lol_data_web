from contextlib import nullcontext
from datetime import datetime, timezone
import json
import logging
from types import SimpleNamespace

import pytest

from scripts import history_worker
from scripts.history_worker import daily_pause_seconds, next_action


def test_history_yields_before_daily_batch_and_resumes_after_window():
    assert daily_pause_seconds(datetime(2026, 10, 3, 23, 39, tzinfo=timezone.utc)) == 0
    assert daily_pause_seconds(datetime(2026, 10, 3, 23, 40, tzinfo=timezone.utc)) == 2400
    assert daily_pause_seconds(datetime(2026, 10, 4, 0, 20, tzinfo=timezone.utc)) == 0


def test_budget_and_lock_do_not_claim_completion():
    assert next_action(4, {"snapshot_completed": False}) == "continue"
    assert next_action(3, {}) == "locked"


def test_no_ready_work_can_still_require_retry_or_attention():
    assert next_action(0, {"snapshot_completed": True}) == "completed"
    assert next_action(2, {"next_retry_at": "2026-10-03T10:00:00Z"}) == "retry_later"
    assert next_action(2, {"has_runnable_work": True}) == "continue"
    assert next_action(2, {}) == "failed"


def test_pending_task_becoming_due_at_batch_end_keeps_worker_running():
    coverage = {
        "snapshot_completed": True,
        "has_runnable_work": True,
        "complete_available": False,
    }
    assert next_action(0, coverage) == "continue"


@pytest.mark.parametrize('interval,expected', [(None, '0.2'), (0, '0'), (0.75, '0.75'), (1, '1')])
def test_worker_passes_interval_to_every_bounded_batch(tmp_path, monkeypatch, interval, expected):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(history_worker, 'daily_pause_seconds', lambda _: 0)
    commands = []

    def run(command, **options):
        commands.append(command)
        assert options['timeout'] == 1080
        assert options['cwd'] == tmp_path
        return SimpleNamespace(returncode=4, stderr='', stdout=json.dumps({'details': {'coverage': {}}}))

    monkeypatch.setattr(history_worker.subprocess, 'run', run)
    parameters = {} if interval is None else {'min_interval': interval}
    assert history_worker.run_worker(400, 900, max_batches=2, **parameters) == 0
    assert len(commands) == 2
    for command in commands:
        assert command[command.index('--min-interval') + 1] == expected
        assert command[command.index('--max-requests') + 1] == '400'
        assert command[command.index('--max-seconds') + 1] == '900'
        assert command[command.index('--phase') + 1] == 'all'


@pytest.mark.parametrize('arguments,expected', [([], 0.2), (['--min-interval', '0.75'], 0.75)])
def test_worker_cli_forwards_default_or_explicit_interval(tmp_path, monkeypatch, arguments, expected):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    monkeypatch.setattr(history_worker.sys, 'argv', ['history_worker', *arguments])
    monkeypatch.setattr(history_worker, 'PipelineLock', lambda _: nullcontext())
    monkeypatch.setattr(history_worker, 'RotatingFileHandler', lambda *args, **kwargs: logging.NullHandler())
    captured = []
    monkeypatch.setattr(history_worker, 'run_worker', lambda *args: captured.append(args) or 0)
    assert history_worker.main() == 0
    assert captured == [(400, 900, None, expected)]


@pytest.mark.parametrize('interval', [-1, float('nan'), float('inf'), float('-inf')])
def test_worker_invalid_interval_rejected_before_runtime_or_cli_output(tmp_path, monkeypatch, interval):
    monkeypatch.setattr(history_worker, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='有限非负'):
        history_worker.run_worker(400, 900, min_interval=interval)
    assert not (tmp_path / 'data').exists()
    monkeypatch.setattr(history_worker.sys, 'argv', ['history_worker', f'--min-interval={interval}'])
    with pytest.raises(SystemExit) as error:
        history_worker.main()
    assert error.value.code == 2
    assert not (tmp_path / 'logs').exists()
