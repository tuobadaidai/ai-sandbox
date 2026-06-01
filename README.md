# AI 沙盒行为洞察系统

通过实战任务评估候选人使用 AI 协同工作的能力。系统以沉浸式沙盒任务为载体，追踪候选人与 AI 的交互行为，自动生成六维度能力评分与认知画像。

## 功能特性

- **三阶段任务评估** — 模糊需求破局 → 动态压力测试 → 事实核查与对抗
- **6 维能力评分** — AI 流利度、人机判断力、架构设计力、混合编排力、认知深度、问题建模能力
- **6 类矛盾信号检测** — 行为轨迹异常光滑、需求变更反应迟缓、事实核查未触发、大量复制粘贴、浅层编辑、未进行问题拆解
- **认知画像生成** — 基于行为轨迹自动产出结构化认知报告
- **行为埋点与事件追踪** — 全程记录编辑、复制粘贴、AI 对话等行为事件
- **管理后台** — 候选人管理、评估触发、报告查看

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python + FastAPI + SQLite |
| 前端 | 原生 JavaScript + CSS（深色主题） |
| AI | 通义千问（DashScope API）/ Mock 模式 |

## 快速开始

### 环境要求

- Python 3.10+

### 启动

```bash
cd ai-sandbox
chmod +x start.sh
./start.sh
```

或手动启动：

```bash
cd ai-sandbox
python3 -m venv venv
source venv/bin/activate
pip install -r server/requirements.txt
mkdir -p data
cd server && python3 main.py
```

### 访问地址

| 页面 | 地址 |
|------|------|
| 候选人入口 | http://localhost:8000 |
| 管理后台 | http://localhost:8000/#admin |
| API 文档 | http://localhost:8000/docs |

### 默认管理密码

```
sandbox-admin-2026
```

## 环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | 空 | 通义千问 API Key，未设置时 AI 聊天不可用 |
| `DASHSCOPE_MODEL` | `qwen-plus` | 使用的模型名称 |
| `SANDBOX_HOST` | `0.0.0.0` | 服务监听地址 |
| `SANDBOX_PORT` | `8000` | 服务监听端口 |
| `ADMIN_SECRET` | `sandbox-admin-2026` | 管理后台访问密码 |

## 项目结构

```
ai-sandbox/
├── start.sh                  # 一键启动脚本
├── data/                     # SQLite 数据库（运行时自动创建）
├── tasks/
│   └── task_v1.json          # 任务配置（三阶段定义）
├── frontend/
│   ├── index.html            # 单页应用入口
│   ├── css/
│   │   └── style.css         # 深色主题样式
│   └── js/
│       ├── sandbox.js        # 沙盒任务逻辑
│       ├── ai-chat.js        # AI 对话组件
│       └── admin.js          # 管理后台逻辑
└── server/
    ├── main.py               # FastAPI 入口 & 路由
    ├── config.py             # 配置（环境变量、路径）
    ├── database.py           # SQLite 数据层
    ├── models.py             # Pydantic 数据模型
    ├── requirements.txt      # Python 依赖
    └── services/
        ├── ai_service.py         # 通义千问 API 封装 & Mock 模式
        ├── behavior_analyzer.py  # 行为叙事生成 & 6 维评分计算
        └── evaluation_engine.py  # 矛盾检测 & 认知画像 & 置信度评估
```

## 使用说明

### 候选人流程

1. 管理员创建候选人，获得专属链接
2. 候选人通过链接进入沙盒，开始三阶段任务（共 30 分钟）
   - **Stage 1**（12 分钟）：将模糊需求转化为可行性分析
   - **Stage 2**（10 分钟）：应对突发需求变更，调整方案
   - **Stage 3**（8 分钟）：核查 AI 输出中的可疑信息
3. 任务过程中可随时与 AI 助手对话
4. 完成后提交最终产出

### 管理员流程

1. 访问管理后台（`/#admin`），输入管理密码
2. 创建候选人并分发专属链接
3. 候选人完成测试后，点击「评估」触发自动评分
4. 查看评估报告：六维度分数、矛盾信号、认知画像

## 部署建议

本项目为轻量级单体应用，适合部署在 Railway、Render 等 PaaS 平台。部署时需配置 `DASHSCOPE_API_KEY` 环境变量，并根据平台要求调整启动命令。

## License

MIT
