import sqlite3

from scripts.backup_database import backup_sqlite


def test_backup_contains_a_consistent_snapshot(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backups" / "snapshot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE facts (value INTEGER)")
        connection.execute("INSERT INTO facts VALUES (42)")
    backup_sqlite(source, destination)
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM facts").fetchone() == (42,)


def test_unknown_api_does_not_return_frontend_html(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.is_json


def test_health_and_initial_sync_status(client):
    assert client.get("/api/health").json["status"] == "ok"
    status = client.get("/api/sync/status")
    assert status.status_code == 200
    assert status.json["last_run"] is None
    assert status.json["schedule"]["enabled"] is False
