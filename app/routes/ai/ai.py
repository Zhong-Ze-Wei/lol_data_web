# app/routes/ai/ai.py
import logging
from flask import Blueprint, request, jsonify
from app.services.ai_assistant import run_ai_query

# 配置日志
logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")


@ai_bp.route("/query", methods=["POST"])
def query_ai():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "无效的请求数据，请提供JSON格式的请求体"}), 400

        prompt = data.get("prompt", "")
        if not prompt:
            return jsonify({"error": "请提供查询内容"}), 400

        result = run_ai_query(prompt)
        return jsonify({"result": result})
    except Exception as e:
        error_msg = f"处理AI查询时出错: {str(e)}"
        logger.exception(error_msg)
        return jsonify({
            "error": error_msg,
            "result": {
                "question": prompt if 'prompt' in locals() else "",
                "answer": f"抱歉，处理您的问题时出现了错误: {str(e)}",
                "error": str(e)
            }
        }), 500
