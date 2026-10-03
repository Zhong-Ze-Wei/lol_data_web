import pytest

from app.models.match import Match
from app.services.ai_assistant import InvalidQuery, execute_readonly, validate_sql


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


def test_ai_provider_timeout_returns_json(client, app, monkeypatch):
    from requests.exceptions import ReadTimeout
    from app.services.ai_assistant import dashscope

    app.config["AI_API_KEY"] = "test-key"
    def unavailable(**kwargs):
        raise ReadTimeout("network timeout")
    monkeypatch.setattr(dashscope.Generation, "call", unavailable)
    response = client.post("/api/ai/query", json={"prompt": "谁的KDA最高"})
    assert response.status_code == 503
    assert response.is_json
