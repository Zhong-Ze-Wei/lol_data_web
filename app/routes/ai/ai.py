import logging

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app.services.ai_assistant import AIUnavailable, InvalidQuery, run_ai_query
from app.services.query_semantics import InvalidPlan, semantic_catalog, validate_context

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")
logger = logging.getLogger(__name__)


@ai_bp.post("/query")
def query_ai():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="请提供 JSON 格式的请求"), 400
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1000:
        return jsonify(error="请输入 1–1000 字的问题"), 400
    prompt = prompt.strip()
    try:
        context = validate_context(data.get("context"))
    except InvalidPlan as error:
        return jsonify(error=str(error)), 400
    try:
        return jsonify(result=run_ai_query(prompt, context=context))
    except AIUnavailable as error:
        return jsonify(error=str(error)), 503
    except InvalidQuery as error:
        return jsonify(error=str(error)), 422
    except SQLAlchemyError:
        logger.exception("AI data query failed")
        return jsonify(error="当前问题无法转换为有效的数据查询，请调整问题"), 422


@ai_bp.get("/catalog")
def analysis_catalog():
    return jsonify(result=semantic_catalog())
