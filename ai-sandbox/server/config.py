# AI 沙盒行为洞察系统 配置文件
import os
from pathlib import Path

# === 基础路径 ===
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TASKS_DIR = BASE_DIR / "tasks"
PROMPTS_DIR = BASE_DIR / "prompts"

DATA_DIR.mkdir(exist_ok=True)

# === 服务器配置 ===
SERVER_HOST = os.getenv("SANDBOX_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SANDBOX_PORT", "8000"))
FRONTEND_DIR = BASE_DIR / "frontend"

# === 数据库 ===
DATABASE_PATH = DATA_DIR / "sandbox.db"

# === 通义千问 API ===
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen-plus")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
AI_MAX_TOKENS = 2048
AI_TEMPERATURE = 0.7

# === 任务配置 ===
DEFAULT_TASK = "task_v1.json"

# === 安全 ===
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "sandbox-admin-2026")
TOKEN_LENGTH = 32
