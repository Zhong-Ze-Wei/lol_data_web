from datetime import datetime, timezone

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
