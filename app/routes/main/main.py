from flask import Blueprint, render_template, request, jsonify
import openai
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 设置 OpenAI API 密钥
openai.api_key = os.getenv('DEEPSEEK_API_KEY')  # 从 .env 文件中获取 API Key

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    return render_template('index.html')

