import json
from contextlib import closing
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app, db as database
from app.models.match import Match
from app.routes.ai import ai as ai_routes
from app.services import ai_assistant
from app.services.ai_assistant import AIUnavailable, InvalidQuery


def query_plan(**overrides):
    return {"type": "query", "subject": "match", "dimensions": [], "metrics": ["games"],
            "filters": {}, "min_games": 1, "order_by": "games", "direction": "desc",
            "limit": 100, "per_group_top_n": None, **overrides}


@pytest.fixture
def ai(app, monkeypatch):
    app.config['AI_API_KEY'] = 'test-only-key'
    reply = Mock(side_effect=[json.dumps(query_plan()), '当前收录1局。'])
    monkeypatch.setattr(ai_assistant, 'model_reply', reply)
    return reply


@pytest.fixture
def one_match(db):
    db.session.add(Match(match_id=1, red_team_name='T1', blue_team_name='GEN', verified=True))
    db.session.commit()


def events(response):
    assert response.status_code == 200
    assert response.mimetype == 'application/x-ndjson'
    return [json.loads(line) for line in response.get_data().splitlines()]


def test_stream_sends_complete_trusted_data_before_writer_is_called(client, ai, one_match):
    with closing(client.post('/api/ai/query-stream', json={'prompt': '收录了多少比赛'}, buffered=False)) as response:
        assert ai.call_count == 1
        iterator = iter(response.response)
        first = json.loads(next(iterator))
        assert first['type'] == 'data'
        result = first['result']
        assert result['data'] == [{'games': 1, 'sample_size': 1, 'matches': 1, 'verified_matches': 1,
                                  'unverified_matches': 0, 'scheduled_matches': 0,
                                  'updated_date_matches': 0, 'unknown_date_matches': 1}]
        assert result['explanation_status'] == 'pending'
        assert result['evidence']['model_calls'] == 1
        assert result['evidence']['timings_ms']['writer'] is None
        for key in ('sql', 'columns', 'assumptions', 'chart', 'context', 'followups'):
            assert key in result
        assert ai.call_count == 1
        explanation = json.loads(next(iterator))
        assert explanation['type'] == 'explanation'
        assert explanation['result']['explanation_status'] == 'complete'
        assert explanation['result']['answer'] == '当前收录1局。'
        assert explanation['result']['data'] == result['data']
        assert explanation['result']['context'] == result['context']
        assert explanation['result']['evidence']['model_calls'] == ai.call_count == 2
        assert json.loads(next(iterator)) == {'type': 'done'}
        with pytest.raises(StopIteration):
            next(iterator)


def test_close_after_first_data_does_not_start_writer(client, ai, one_match):
    with closing(client.post('/api/ai/query-stream', json={'prompt': '收录比赛局数'}, buffered=False)) as response:
        assert json.loads(next(iter(response.response)))['type'] == 'data'
        assert ai.call_count == 1
    # GeneratorExit at the first yield must never finish the explanation.
    assert ai.call_count == 1


@pytest.mark.parametrize('path', ['/api/ai/query', '/api/ai/query-stream'])
def test_explain_false_returns_deterministic_result_without_second_call(client, ai, one_match, path):
    response = client.post(path, json={'prompt': '收录比赛局数', 'explain': False})
    if path.endswith('-stream'):
        emitted = events(response)
        assert [item['type'] for item in emitted] == ['data', 'done']
        result = emitted[0]['result']
    else:
        result = response.json['result']
    assert result['data'][0]['games'] == 1
    assert result['explanation_status'] == 'skipped'
    assert result['evidence']['model_calls'] == ai.call_count == 1
    assert result['evidence']['timings_ms']['writer'] is None
    assert '查询得到' in result['answer']


@pytest.mark.parametrize('path', ['/api/ai/query', '/api/ai/query-stream'])
@pytest.mark.parametrize('explain', [None, 'false', 0, []])
def test_explain_requires_a_real_boolean_before_calling_model(client, ai, path, explain):
    response = client.post(path, json={'prompt': '比赛局数', 'explain': explain})
    assert response.status_code == 400 and response.is_json
    assert '布尔' in response.json['error']
    ai.assert_not_called()


@pytest.mark.parametrize('body', [None, {'prompt': 123}, {'prompt': ''}, {'prompt': 'a' * 1001},
                                  {'prompt': '比赛局数', 'context': {'sql': 'SELECT 1'}}])
def test_stream_invalid_input_returns_json_before_stream_headers(client, ai, body):
    response = client.post('/api/ai/query-stream', json=body)
    assert response.status_code == 400 and response.is_json
    ai.assert_not_called()


def test_stream_missing_key_returns_json_before_stream_headers(client, app, ai):
    app.config['AI_API_KEY'] = ''
    response = client.post('/api/ai/query-stream', json={'prompt': '收录比赛局数'})
    assert response.status_code == 503 and response.is_json
    ai.assert_not_called()


@pytest.mark.parametrize('error,code', [(AIUnavailable('AI 暂时不可用'), 503),
                                       (InvalidQuery('计划不能执行'), 422)])
def test_stream_planning_error_returns_json_before_stream_headers(client, ai, error, code):
    ai.side_effect = error
    response = client.post('/api/ai/query-stream', json={'prompt': '收录比赛局数'})
    assert response.status_code == code and response.is_json
    assert response.json['error'] == str(error)
    assert ai.call_count == 1


def test_stream_query_timeout_does_not_spend_repair_or_writer_call(client, ai, one_match, monkeypatch):
    execute = Mock(side_effect=OperationalError('SELECT', {}, Exception('interrupted')))
    monkeypatch.setattr(ai_assistant, 'execute_readonly_batch', execute)
    response = client.post('/api/ai/query-stream', json={'prompt': '收录比赛局数'})
    assert response.status_code == 422 and response.is_json
    assert ai.call_count == 1


@pytest.mark.parametrize('reply,status', [
    ({'type': 'unsupported', 'reason': '没有此字段'}, 'unsupported'),
    ({'type': 'clarify', 'question': '请明确指标', 'choices': [{'label': '局数', 'prompt': '收录比赛局数'}]}, 'needs_clarification'),
    (query_plan(dimensions=['tournament'], filters={'tournament_contains': ['不存在']}), 'empty'),
])
def test_non_query_or_empty_results_finish_without_writer(client, ai, reply, status):
    ai.side_effect = None
    ai.return_value = json.dumps(reply)
    emitted = events(client.post('/api/ai/query-stream', json={'prompt': '查询比赛情况'}))
    assert [item['type'] for item in emitted] == ['data', 'done']
    result = emitted[0]['result']
    assert result['status'] == status and result['explanation_status'] == 'skipped'
    assert ai.call_count == result['evidence']['model_calls'] == 1
    timings = result['evidence']['timings_ms']
    assert timings['repair'] is timings['writer'] is None
    if status != 'empty':
        assert timings['compile'] is timings['query'] is None


@pytest.mark.parametrize('prompt,status', [('谁最强？', 'needs_clarification'),
                                         ('哪个补丁版本英雄ban率最高', 'unsupported')])
def test_local_clarification_and_unsupported_use_zero_model_calls(client, ai, prompt, status):
    emitted = events(client.post('/api/ai/query-stream', json={'prompt': prompt}))
    assert [item['type'] for item in emitted] == ['data', 'done']
    result = emitted[0]['result']
    assert result['status'] == status and result['explanation_status'] == 'skipped'
    assert result['evidence']['model_calls'] == 0
    for phase in ('catalog', 'planning', 'repair', 'compile', 'query', 'writer'):
        assert result['evidence']['timings_ms'][phase] is None
    ai.assert_not_called()


def test_plan_format_repair_uses_second_call_and_skips_writer(client, ai, one_match):
    ai.side_effect = ['not JSON', json.dumps(query_plan())]
    emitted = events(client.post('/api/ai/query-stream', json={'prompt': '比赛局数'}))
    assert [item['type'] for item in emitted] == ['data', 'done']
    result = emitted[0]['result']
    assert result['data'][0]['games'] == 1
    assert result['evidence']['model_calls'] == ai.call_count == 2
    assert result['evidence']['repaired'] is True and result['explanation_status'] == 'skipped'
    assert result['evidence']['timings_ms']['repair'] is not None
    assert result['evidence']['timings_ms']['writer'] is None


def test_database_repair_does_not_call_a_third_model(client, ai, one_match, monkeypatch):
    actual = ai_assistant.execute_readonly_batch
    queries = 0

    def execute(statements, timeout):
        nonlocal queries
        queries += 1
        if queries == 1:
            raise OperationalError('SELECT', {}, Exception('no such column: internal_schema'))
        return actual(statements, timeout)

    ai.side_effect = [json.dumps(query_plan()), json.dumps(query_plan())]
    monkeypatch.setattr(ai_assistant, 'execute_readonly_batch', execute)
    emitted = events(client.post('/api/ai/query-stream', json={'prompt': '收录比赛局数'}))
    assert [item['type'] for item in emitted] == ['data', 'done']
    result = emitted[0]['result']
    assert result['evidence']['model_calls'] == ai.call_count == queries == 2
    assert result['evidence']['repaired'] is True and result['explanation_status'] == 'skipped'
    assert result['evidence']['timings_ms']['repair'] is not None
    assert result['evidence']['timings_ms']['writer'] is None


def test_writer_failure_preserves_snapshot_and_emits_final_fallback(client, ai, one_match):
    ai.side_effect = [json.dumps(query_plan()), AIUnavailable('文字暂时不可用')]
    emitted = events(client.post('/api/ai/query-stream', json={'prompt': '比赛局数'}))
    assert [item['type'] for item in emitted] == ['data', 'explanation', 'done']
    initial, final = emitted[0]['result'], emitted[1]['result']
    assert final['explanation_status'] == 'unavailable'
    assert final['data'] == initial['data'] and final['answer'] == initial['answer']
    assert final['sql'] == initial['sql'] and final['context'] == initial['context']
    assert final['evidence']['model_calls'] == ai.call_count == 2
    assert any('文字解读暂时不可用' in text for text in final['assumptions'])
    assert final['evidence']['timings_ms']['writer'] is not None


def test_expected_error_after_headers_is_an_error_event(client, ai, one_match, monkeypatch):
    monkeypatch.setattr(ai_routes, 'finish_ai_explanation', Mock(side_effect=InvalidQuery('解读无法继续')))
    emitted = events(client.post('/api/ai/query-stream', json={'prompt': '比赛局数'}))
    assert [item['type'] for item in emitted] == ['data', 'error', 'done']
    assert emitted[1] == {'type': 'error', 'error': '解读无法继续', 'code': 422}
    assert emitted[0]['result']['data'][0]['games'] == 1
    assert ai.call_count == 1


def test_client_rows_and_sql_are_never_used_as_explanation_data(client, ai, one_match):
    emitted = events(client.post('/api/ai/query-stream', json={
        'prompt': '比赛局数', 'rows': [{'games': 999999}], 'sql': 'DELETE FROM matches',
    }))
    actual = emitted[0]['result']['data']
    assert actual[0]['games'] == 1
    supplied = json.loads(ai.call_args_list[1].args[1])
    assert supplied['rows'] == actual and 'DELETE' not in supplied['question']


def test_phase_timings_measure_actual_work_and_leave_unexecuted_phases_null(client, ai, one_match, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(ai_assistant.time, 'monotonic', lambda: clock[0])
    catalog = ai_assistant.entity_catalog
    prepare = ai_assistant.prepare_query
    execute = ai_assistant.execute_readonly_batch

    def timed_catalog():
        clock[0] += .003
        return catalog()

    def timed_prepare(plan):
        clock[0] += .005
        return prepare(plan)

    def timed_execute(statements, timeout):
        clock[0] += .007
        return execute(statements, timeout)

    replies = 0

    def reply(system, prompt):
        nonlocal replies
        replies += 1
        clock[0] += .011 if replies == 1 else .013
        return json.dumps(query_plan()) if replies == 1 else '统计完成'

    ai.side_effect = reply
    monkeypatch.setattr(ai_assistant, 'entity_catalog', timed_catalog)
    monkeypatch.setattr(ai_assistant, 'prepare_query', timed_prepare)
    monkeypatch.setattr(ai_assistant, 'execute_readonly_batch', timed_execute)
    emitted = events(client.post('/api/ai/query-stream', json={'prompt': '比赛局数'}))
    initial = emitted[0]['result']['evidence']['timings_ms']
    final = emitted[1]['result']['evidence']['timings_ms']
    assert initial == {'catalog': 3, 'planning': 11, 'repair': None, 'compile': 5, 'query': 7,
                       'writer': None, 'data_ready': 26, 'service': 26}
    assert final == {**initial, 'writer': 13, 'service': 39}
    assert emitted[0]['result']['evidence']['query_ms'] == 7


def test_new_catalog_transaction_is_released_before_planner_or_writer(db, ai, one_match):
    seen = []

    def reply(system, prompt):
        assert not db.session.registry.has()
        seen.append(system)
        return json.dumps(query_plan()) if len(seen) == 1 else '完成'

    ai.side_effect = reply
    result = ai_assistant.run_ai_query('比赛局数')
    assert result['explanation_status'] == 'complete' and len(seen) == 2


def test_existing_caller_read_transaction_is_not_closed_by_catalog(tmp_path, monkeypatch):
    path = tmp_path / 'read-snapshot.sqlite'
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{path.as_posix()}',
                      'DATA_DIR': tmp_path, 'AUTO_CREATE_DB': False, 'AI_API_KEY': 'test-only-key'})
    monkeypatch.setattr(ai_assistant, 'model_reply', Mock(side_effect=[json.dumps(query_plan()), '完成']))
    with app.app_context():
        database.create_all()
        database.session.add(Match(match_id=1, verified=True))
        database.session.commit()
        session = database.session()
        connection = session.connection()
        connection.exec_driver_sql('BEGIN')
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM matches').scalar_one() == 1
        raw = connection.connection.driver_connection
        result = ai_assistant.run_ai_query('比赛局数')
        assert result['data'][0]['games'] == 1
        assert database.session() is session and session.in_transaction() and raw.in_transaction
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM matches').scalar_one() == 1
        session.rollback()
        database.session.remove()
        database.engine.dispose()


def test_existing_caller_pending_write_is_not_autoflushed_or_rolled_back(tmp_path, monkeypatch):
    path = tmp_path / 'pending-write.sqlite'
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{path.as_posix()}',
                      'DATA_DIR': tmp_path, 'AUTO_CREATE_DB': False, 'AI_API_KEY': 'test-only-key'})
    monkeypatch.setattr(ai_assistant, 'model_reply', Mock(side_effect=[json.dumps(query_plan()), '完成']))
    with app.app_context():
        database.create_all()
        database.session.add(Match(match_id=1, verified=True))
        database.session.commit()
        pending = Match(match_id=2, verified=True)
        session = database.session()
        session.add(pending)
        result = ai_assistant.run_ai_query('比赛局数')
        assert result['data'][0]['games'] == 1
        assert database.session() is session and pending in session.new and pending.id is None
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT COUNT(*) FROM matches').scalar_one() == 1
        session.rollback()
        database.session.remove()
        database.engine.dispose()


def test_completed_explanation_cannot_spend_another_call(ai, one_match):
    prepared = ai_assistant.prepare_ai_query('比赛局数')
    first = ai_assistant.finish_ai_explanation(prepared)
    again = ai_assistant.finish_ai_explanation(prepared)
    assert again['answer'] == first['answer'] == '当前收录1局。'
    assert again['evidence']['model_calls'] == ai.call_count == 2
