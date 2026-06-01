#!/bin/bash
echo "========================================="
echo "  AI 沙盒行为洞察系统"
echo "========================================="

cd "$(dirname "$0")"

# === 环境检测 ===
if [ ! -d "venv" ]; then
  echo "[1/4] 创建虚拟环境..."
  python3 -m venv venv
else
  echo "[0/4] 使用已有虚拟环境"
fi

source venv/bin/activate

# === 依赖安装 ===
echo "[1/4] 检查依赖..."
pip install -q -r server/requirements.txt 2>/dev/null

# === 数据目录 ===
mkdir -p data

# === AI 后端配置 ===
echo "[2/4] 配置 AI 后端..."
if [ -n "$DASHSCOPE_API_KEY" ]; then
  echo "  → 使用 DashScope (阿里云) 后端"
  echo "  → 模型: ${DASHSCOPE_MODEL:-qwen-plus}"
else
  # 默认使用本地 Ollama
  export AI_BASE_URL="${AI_BASE_URL:-http://localhost:11434/v1}"
  export AI_MODEL="${AI_MODEL:-qwen2:1.5b}"
  export AI_API_KEY="${AI_API_KEY:-ollama}"
  echo "  → 使用本地 Ollama 后端"
  echo "  → 模型: $AI_MODEL"
  echo "  → 地址: $AI_BASE_URL"
  
  # 检测 Ollama 是否运行
  if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  ⚠️  警告: Ollama 服务未运行，请先执行 'ollama serve'"
  fi
fi

# === 启动服务 ===
echo "[3/4] 启动后端服务..."
echo "[4/4] 访问地址:"
echo "   本地访问: http://localhost:8000"
echo "   管理后台: http://localhost:8000/#admin"
echo "   API文档:  http://localhost:8000/docs"
echo ""
echo "   管理密码: sandbox-admin-2026"
echo "========================================="

cd server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
