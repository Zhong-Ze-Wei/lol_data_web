"""真实 HTTP 首块验收；只使用临时数据库和受控模型，不访问模型服务。"""

import json
import threading

import requests
from waitress import create_server

from app import create_app, db
from app.models.match import Match
from app.services import ai_assistant


def test_waitress_delivers_data_before_writer_finishes_without_snapshot_drift(tmp_path, monkeypatch):
    database_file = tmp_path / "stream.db"
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_file.as_posix()}",
        "DATA_DIR": tmp_path / "data",
        "AI_API_KEY": "test-only-key",
        "AUTO_CREATE_DB": True,
    })
    with app.app_context():
        db.session.add(Match(match_id=1, red_team_name="T1", blue_team_name="GEN", verified=True))
        db.session.commit()

    writer_entered = threading.Event()
    release_writer = threading.Event()
    writer_finished = threading.Event()
    writer_inputs = []
    plan = {"type": "query", "subject": "match", "dimensions": [], "metrics": ["games"],
            "filters": {}, "min_games": 1, "order_by": "games", "direction": "desc",
            "limit": 1, "per_group_top_n": None}

    def controlled_model(system, prompt):
        payload = json.loads(prompt)
        if "rows" not in payload:
            return json.dumps(plan)
        writer_inputs.append(payload)
        writer_entered.set()
        assert release_writer.wait(10), "首块如果被缓冲，客户端无法释放解读阶段"
        writer_finished.set()
        return "本次查询快照收录1局比赛。"

    monkeypatch.setattr(ai_assistant, "model_reply", controlled_model)
    server = create_server(app, host="127.0.0.1", port=0, threads=2, map={}, asyncore_loop_timeout=0.05)
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    endpoint = f"http://127.0.0.1:{server.effective_port}/api/ai/query-stream"
    try:
        with requests.post(endpoint, json={"prompt": "收录了多少局比赛？"}, stream=True, timeout=(3, 5)) as response:
            assert response.status_code == 200
            assert response.headers["Content-Type"].startswith("application/x-ndjson")
            lines = response.iter_lines(chunk_size=1)
            first = json.loads(next(lines))
            assert first["type"] == "data"
            assert first["result"]["data"][0]["games"] == 1
            assert first["result"]["explanation_status"] == "pending"
            assert not writer_finished.is_set()
            assert writer_entered.wait(3)
            # 第一事件以后采集新行，不能改变解读使用的已完成查询快照。
            with app.app_context():
                db.session.add(Match(match_id=2, red_team_name="IG", blue_team_name="BLG", verified=True))
                db.session.commit()
            release_writer.set()
            remaining = [json.loads(line) for line in lines if line]
            assert [event["type"] for event in remaining] == ["explanation", "done"]
            final = remaining[0]["result"]
            assert final["data"] == first["result"]["data"]
            assert final["evidence"]["rows"] == first["result"]["evidence"]["rows"] == 1
            assert final["context"] == first["result"]["context"]
            assert final["explanation_status"] == "complete"
            assert final["evidence"]["model_calls"] == 2
            assert len(writer_inputs) == 1
            assert writer_inputs[0]["rows"] == first["result"]["data"]
            assert writer_inputs[0]["evidence"]["rows"] == 1
        with app.app_context():
            assert Match.query.count() == 2
            db.session.remove()
            db.engine.dispose()
    finally:
        release_writer.set()
        server.task_dispatcher.shutdown()
        for channel in list(server._map.values()):
            channel.close()
        worker.join(3)
        assert not worker.is_alive()
