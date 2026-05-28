#!/bin/bash
# AI 沙盒行为洞察系统 - 一键启动脚本
# 用法: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$SCRIPT_DIR/server"

echo "========================================="
echo "  AI 沙盒行为洞察系统"
echo "========================================="

# 确保虚拟环境存在
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -f "$VENV_DIR/bin/python3" ]; then
    echo "[0/3] 创建虚拟环境..."
    /opt/homebrew/bin/python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q -r "$SERVER_DIR/requirements.txt"
else
    echo "[0/3] 使用已有虚拟环境"
fi
PYTHON="$VENV_DIR/bin/python3"

# 创建数据目录
mkdir -p "$SCRIPT_DIR/data"

# 设置环境变量（如果未设置）
export DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-}"

if [ -z "$DASHSCOPE_API_KEY" ]; then
    echo ""
    echo "⚠️  警告: 未设置 DASHSCOPE_API_KEY"
    echo "   AI 聊天功能将不可用"
    echo "   设置方法: export DASHSCOPE_API_KEY='your-key'"
    echo ""
fi

# 启动服务
echo "[2/3] 启动后端服务..."
echo "[3/3] 访问地址:"
echo ""
echo "   本地访问: http://localhost:8000"
echo "   管理后台: http://localhost:8000/#admin"
echo "   API文档:  http://localhost:8000/docs"
echo ""

cd "$SERVER_DIR"
$PYTHON main.py
