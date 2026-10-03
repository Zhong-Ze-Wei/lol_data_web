import json
import logging

from flask import Blueprint, Response, jsonify, request, stream_with_context
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import BadRequest

from app.services.ai_assistant import (
    AIUnavailable, InvalidQuery, finish_ai_explanation, prepare_ai_query, run_ai_query,
)
from app.services.query_semantics import InvalidPlan, semantic_catalog, validate_context

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")
logger = logging.getLogger(__name__)


def _query_parameters():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("请提供 JSON 格式的请求")
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1000:
        raise BadRequest("请输入 1–1000 字的问题")
    prompt = prompt.strip()
    explain = data.get("explain", True)
    if not isinstance(explain, bool):
        raise BadRequest("explain 必须是布尔值")
    try:
        context = validate_context(data.get("context"))
    except InvalidPlan as error:
        raise BadRequest(str(error)) from error
    return {"user_prompt": prompt, "context": context, "explain": explain}


def _query_error(error):
    if isinstance(error, AIUnavailable):
        return str(error), 503
    if isinstance(error, InvalidQuery):
        return str(error), 422
    logger.exception("AI data query failed")
    return "当前问题无法转换为有效的数据查询，请调整问题", 422


@ai_bp.post("/query")
def query_ai():
    parameters = _query_parameters()
    try:
        return jsonify(result=run_ai_query(**parameters))
    except (AIUnavailable, InvalidQuery, SQLAlchemyError) as error:
        message, code = _query_error(error)
        return jsonify(error=message), code


def _query_events(prepared):
    # 首个 yield 之前已完成同快照查询，暂停/关闭此生成器不会启动 writer。
    yield json.dumps({"type": "data", "result": prepared.result}, ensure_ascii=False) + "\n"
    try:
        if prepared.result["explanation_status"] == "pending":
            result = finish_ai_explanation(prepared)
            yield json.dumps({"type": "explanation", "result": result}, ensure_ascii=False) + "\n"
    except (AIUnavailable, InvalidQuery, SQLAlchemyError) as error:
        message, code = _query_error(error)
        yield json.dumps({"type": "error", "error": message, "code": code}, ensure_ascii=False) + "\n"
    yield '{"type":"done"}\n'


@ai_bp.post("/query-stream")
def query_ai_stream():
    parameters = _query_parameters()
    try:
        # 先准备数据，校验、密钥、planner 和 SQL 错误仍在 headers 发送前返回 JSON。
        prepared = prepare_ai_query(**parameters)
    except (AIUnavailable, InvalidQuery, SQLAlchemyError) as error:
        message, code = _query_error(error)
        return jsonify(error=message), code
    return Response(stream_with_context(_query_events(prepared)), mimetype="application/x-ndjson",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@ai_bp.get("/catalog")
def analysis_catalog():
    return jsonify(result=semantic_catalog())
