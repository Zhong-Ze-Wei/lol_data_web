import json
from unittest.mock import Mock

import pytest
from requests.exceptions import ConnectionError, ReadTimeout

from app.models.match import Match
from app.services import ai_assistant
from app.services.ai_assistant import InvalidQuery, execute_readonly, model_reply, validate_sql


@pytest.fixture
def ai_config(app):
    app.config.update(
        AI_API_KEY="test-only-key",
        AI_BASE_URL="https://aiping.cn/api/v1/",
        AI_MODEL="DeepSeek-V4.1-Flash",
        AI_MAX_TOKENS=2048,
        AI_TIMEOUT=45,
    )
    return app


@pytest.fixture
def provider_post(monkeypatch):
    post = Mock()
    monkeypatch.setattr(ai_assistant.requests, "post", post)
    return post


def completion(content, finish_reason="stop"):
    return Mock(status_code=200, json=Mock(return_value={
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
    }))


def query_plan(**overrides):
    return {"type": "query", "subject": "match", "dimensions": [], "metrics": ["games"],
            "filters": {}, "min_games": 1, "order_by": "games", "direction": "desc",
            "limit": 100, "per_group_top_n": None, **overrides}


@pytest.mark.parametrize("sql", [
    "DELETE FROM players", "SELECT 1; DROP TABLE matches",
    "SELECT * FROM sqlite_master", "SELECT * FROM other.players",
    "SELECT randomblob(1000000)", "SELECT * INTO OUTFILE 'x' FROM players",
])
def test_ai_rejects_non_readonly_queries(sql):
    with pytest.raises(InvalidQuery):
        validate_sql(sql, "sqlite")


def test_ai_limits_rows_and_allows_cte():
    sql = validate_sql("WITH p AS (SELECT name FROM players) SELECT name FROM p", "sqlite", 10)
    assert "LIMIT 10" in sql


def test_ai_readonly_connection_is_restored(db):
    assert execute_readonly(validate_sql("SELECT 1 AS n", "sqlite")) == [{"n": 1}]
    db.session.add(Match(match_id=1, red_team_name="T1", blue_team_name="GEN", win_team_name="T1"))
    db.session.commit()
    assert Match.query.count() == 1


def test_ai_missing_key_is_explicit(client):
    response = client.post("/api/ai/query", json={"prompt": "谁的KDA最高"})
    assert response.status_code == 503
    assert "密钥" in response.json["error"]


def test_ai_validates_prompt(client):
    assert client.post("/api/ai/query", json={"prompt": 123}).status_code == 400


def test_nested_cte_cannot_shadow_a_real_private_table():
    sql = "WITH allowed AS (WITH sync_runs AS (SELECT 1 AS x) SELECT x FROM sync_runs) SELECT command,details FROM sync_runs"
    with pytest.raises(InvalidQuery):
        validate_sql(sql, "sqlite")


def test_ai_preserves_the_requested_small_limit():
    sql = validate_sql("SELECT name FROM players ORDER BY kills DESC LIMIT 3", "sqlite", 100)
    assert sql.endswith("LIMIT 3")


def test_mysql_connection_functions_are_rejected():
    with pytest.raises(InvalidQuery):
        validate_sql("SELECT GET_LOCK('test',10)", "mysql")


@pytest.mark.parametrize("network_error", [ReadTimeout, ConnectionError])
def test_ai_provider_network_failure_returns_safe_json(client, ai_config, provider_post, caplog, network_error):
    provider_post.side_effect = network_error("test-only-key should never appear")
    response = client.post("/api/ai/query", json={"prompt": "谁的KDA最高"})
    assert response.status_code == 503
    assert response.is_json
    assert "test-only-key" not in response.get_data(as_text=True)
    assert "test-only-key" not in caplog.text
    assert provider_post.call_count == 1


def test_ai_sends_openai_compatible_request(ai_config, provider_post):
    provider_post.return_value = completion("  SELECT 1  ")
    assert model_reply("只返回 SQL", "比赛数量") == "SELECT 1"
    provider_post.assert_called_once_with(
        "https://aiping.cn/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-only-key"},
        json={
            "model": "DeepSeek-V4.1-Flash",
            "messages": [{"role": "system", "content": "只返回 SQL"}, {"role": "user", "content": "比赛数量"}],
            "temperature": 0.1,
            "stream": False,
            "max_tokens": 2048,
            "enable_thinking": False,
        },
        timeout=45,
    )


@pytest.mark.parametrize("status, message", [
    (401, "密钥"), (403, "权限"), (429, "频繁"), (500, "暂时不可用"), (502, "暂时不可用"),
])
def test_ai_provider_http_errors_do_not_expose_provider_data(client, ai_config, provider_post, caplog, status, message):
    provider_post.return_value = Mock(
        status_code=status,
        text="provider diagnostic includes test-only-key",
        json=Mock(return_value={"error": "provider diagnostic includes test-only-key"}),
    )
    response = client.post("/api/ai/query", json={"prompt": "比赛数量"})
    assert response.status_code == 503
    assert message in response.json["error"]
    assert "test-only-key" not in response.get_data(as_text=True)
    assert "test-only-key" not in caplog.text
    assert str(status) in caplog.text
    assert provider_post.call_count == 1
    provider_post.return_value.json.assert_not_called()


@pytest.mark.parametrize("payload", [
    {}, {"choices": []}, {"choices": None}, {"choices": [{"message": {}}]},
    {"choices": [{"message": None}]}, {"choices": [None]},
])
def test_ai_rejects_invalid_provider_response_structure(client, ai_config, provider_post, payload):
    provider_post.return_value = Mock(status_code=200, json=Mock(return_value=payload))
    response = client.post("/api/ai/query", json={"prompt": "比赛数量"})
    assert response.status_code == 503
    assert "无效结果" in response.json["error"]


def test_ai_rejects_non_json_provider_response(client, ai_config, provider_post):
    provider_post.return_value = Mock(status_code=200, json=Mock(side_effect=ValueError("invalid JSON")))
    response = client.post("/api/ai/query", json={"prompt": "比赛数量"})
    assert response.status_code == 503
    assert "无效结果" in response.json["error"]


@pytest.mark.parametrize("content", ["", " \n ", None, [], 42])
def test_ai_rejects_empty_or_non_text_content(client, ai_config, provider_post, content):
    provider_post.return_value = completion(content)
    response = client.post("/api/ai/query", json={"prompt": "比赛数量"})
    assert response.status_code == 503
    assert "有效内容" in response.json["error"]


def test_ai_never_executes_a_truncated_sql_response(client, ai_config, provider_post, monkeypatch):
    provider_post.return_value = completion("SELECT COUNT(*) FROM matches", finish_reason="length")
    execute = Mock()
    monkeypatch.setattr(ai_assistant, "execute_readonly_batch", execute)
    response = client.post("/api/ai/query", json={"prompt": "比赛数量"})
    assert response.status_code == 503
    assert "长度限制" in response.json["error"]
    execute.assert_not_called()
    assert provider_post.call_count == 1


def test_ai_queries_database_then_answers_using_returned_rows(client, ai_config, provider_post, db):
    db.session.add_all([
        Match(match_id=1, red_team_name="T1", blue_team_name="GEN", verified=True),
        Match(match_id=2, red_team_name="T1", blue_team_name="GEN", verified=False),
    ])
    db.session.commit()
    provider_post.side_effect = [
        completion(json.dumps(query_plan(filters={"verified_only": True}))),
        completion("当前收录并已核验的比赛共 **1 局**。"),
    ]
    response = client.post("/api/ai/query", json={"prompt": "已经核验了多少局比赛？"})
    assert response.status_code == 200
    assert response.json["result"]["data"][0]["games"] == 1
    assert response.json["result"]["answer"] == "当前收录并已核验的比赛共 **1 局**。"
    assert "LIMIT 100" in response.json["result"]["sql"]
    assert provider_post.call_count == 2
    answer_prompt = json.loads(provider_post.call_args_list[1].kwargs["json"]["messages"][1]["content"])
    assert answer_prompt["question"] == "已经核验了多少局比赛？"
    assert answer_prompt["rows"] == response.json["result"]["data"]
    assert answer_prompt["evidence"]["verified_matches"] == 1


def test_ai_empty_query_results_do_not_make_another_provider_call(client, ai_config, provider_post):
    provider_post.return_value = completion(json.dumps(query_plan(dimensions=["tournament"], filters={"tournament_contains": ["not-in-data"]})))
    response = client.post("/api/ai/query", json={"prompt": "查找不存在的比赛"})
    assert response.status_code == 200
    assert response.json["result"]["data"] == []
    assert "没有符合" in response.json["result"]["answer"]
    assert provider_post.call_count == 1
