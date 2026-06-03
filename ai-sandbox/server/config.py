import os
from pathlib import Path

# === 路径配置 ===
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
TASKS_DIR = BASE_DIR / "tasks"
FRONTEND_DIR = BASE_DIR / "frontend"
DATABASE_PATH = DATA_DIR / "sandbox.db"

# === 服务器配置 ===
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# === 任务配置 ===
DEFAULT_TASK = os.getenv("DEFAULT_TASK", "task_v3_valid.json")

# === 管理后台 ===
# 安全：不再硬编码默认密码，必须通过环境变量设置
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
if not ADMIN_SECRET:
    # 开发模式回退，生产环境必须设置环境变量
    ADMIN_SECRET = os.getenv("ADMIN_SECRET_DEV", "dev-only-change-me")
ADMIN_SESSION_EXPIRY = int(os.getenv("ADMIN_SESSION_EXPIRY", "86400"))  # 会话过期秒数，默认24h
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")  # 逗号分隔的允许域名，为空则用同源策略
TOKEN_LENGTH = 16

# === AI 服务配置 ===
# DashScope (生产环境 / 阿里云)
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen-plus")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Ollama / 通用 OpenAI 兼容 (本地开发)
AI_API_KEY = os.getenv("AI_API_KEY", "ollama")
AI_MODEL = os.getenv("AI_MODEL", "qwen2:1.5b")
AI_BASE_URL = os.getenv("AI_BASE_URL", "http://localhost:11434/v1")

# AI 参数
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "2048"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.7"))
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "60"))
AI_MAX_RETRIES = 3

def get_active_config():
    """获取当前活跃的 AI 配置，优先 DashScope"""
    if DASHSCOPE_API_KEY:
        return {
            "api_key": DASHSCOPE_API_KEY,
            "model": DASHSCOPE_MODEL,
            "base_url": DASHSCOPE_BASE_URL,
        }
    return {
        "api_key": AI_API_KEY,
        "model": AI_MODEL,
        "base_url": AI_BASE_URL,
    }
